<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Sovereign\Repositories\NormalizesMemberRows;
use AltContext\Sovereign\Repositories\RosterEntryProjectionRepository;
use AltContext\Tests\Stubs\NullSyncStateRepository;
use AltContext\Tests\TestCase;

require_once dirname(__DIR__, 2) . '/src/sovereign/repositories/trait-normalizes-member-rows.php';

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

	/**
	 * HARM-BR-03: last_sync_result resync_required (rekey / threshold) must surface
	 * as projection_status 'stale', not 'current'. RosterPage gates workspace entry
	 * and staleness notice on projectionStatus !== 'current'; reporting current while
	 * the sync strip says "Re-sync required" hides an invalid projection.
	 *
	 * Exhaustive mapping (closed SyncStateRepository::SYNC_RESULT_* set): every
	 * durable last_sync_result maps to its expected projection_status, including
	 * inputs that must NOT map to 'stale'. assertNotSame('current') is entailed by
	 * assertSame('stale') and does not catch resync_required → failed/refreshing.
	 */
	public function testListEntriesReportsStaleProjectionWhenResyncRequired(): void
	{
		$this->seedRosterRows();

		// Closed-set mapping with lastUpdated set (so null-refresh is not the stale cause).
		$expectedBySyncResult = [
			'resync_required' => 'stale',
			'ok' => 'current',
			'failed' => 'failed',
			'unreachable' => 'failed',
		];

		foreach ($expectedBySyncResult as $syncResult => $expectedProjection) {
			$repository = new RosterEntryProjectionRepository(
				new RosterEntryProjectionSyncStateSpy(
					snapshotVersion: 42,
					lastUpdated: '2026-05-07 16:00:00',
					lastSyncResult: $syncResult
				)
			);

			$data = $repository->list_entries(self::currentTenantId());

			$this->assertSame(
				$expectedProjection,
				$data[0]['projection_status'],
				"last_sync_result '{$syncResult}' must map to projection_status '{$expectedProjection}'"
			);
		}

		// Fixture metadata for the resync_required arm (load-bearing stale contract).
		$repository = new RosterEntryProjectionRepository(
			new RosterEntryProjectionSyncStateSpy(
				snapshotVersion: 42,
				lastUpdated: '2026-05-07 16:00:00',
				lastSyncResult: 'resync_required'
			)
		);
		$data = $repository->list_entries(self::currentTenantId());
		$this->assertSame('2026-05-07 16:00:00', $data[0]['projection_refreshed_at']);
		$this->assertSame(42, $data[0]['source_version']);
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

	/**
	 * Survivor policy (E21-9): rows that normalize equal collapse to lowest-id primary;
	 * clusters and queue_memberships are unions of member rows (rg-015).
	 * Targets residual uniqueness gap after collation pin — not states UNIQUE forbids.
	 */
	public function testListEntriesGroupsByNormalizedNameWithLowestIdSurvivorAndUnionedAggregates(): void
	{
		global $wpdb;

		$wpdb->tableRows['wp_acx_persons'] = [
			[
				'id' => 10,
				'person_uuid' => 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
				'name' => 'José',
				'normalized_name' => 'josé',
				'tags' => '["primary"]',
				'queue_memberships_json' => '["hard-examples"]',
				'cluster_count' => 0,
				'updated_at' => '2026-05-07 14:00:00',
			],
			[
				// Higher id, same normalized_name residual (dirty-dev defense-in-depth).
				'id' => 20,
				'person_uuid' => 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb',
				'name' => 'José',
				'normalized_name' => 'josé',
				'tags' => '["secondary"]',
				'queue_memberships_json' => '["singleton-proposals"]',
				'cluster_count' => 0,
				'updated_at' => '2026-05-07 15:00:00',
			],
			[
				'id' => 30,
				'person_uuid' => 'cccccccc-cccc-cccc-cccc-cccccccccccc',
				'name' => 'Jose',
				'normalized_name' => 'jose',
				'tags' => '[]',
				'updated_at' => '2026-05-07 16:00:00',
			],
		];
		$wpdb->tableRows['wp_acx_clusters'] = [
			[
				'cluster_uuid' => 'cluster-primary',
				'person_id' => 10,
				'identity_count' => 1,
				'representative_id' => 'identity-p',
				'updated_at' => '2026-05-07 14:10:00',
			],
			[
				'cluster_uuid' => 'cluster-secondary',
				'person_id' => 20,
				'identity_count' => 1,
				'representative_id' => 'identity-s',
				'updated_at' => '2026-05-07 15:10:00',
			],
			[
				'cluster_uuid' => 'cluster-ascii',
				'person_id' => 30,
				'identity_count' => 1,
				'representative_id' => 'identity-a',
				'updated_at' => '2026-05-07 16:10:00',
			],
		];
		$wpdb->tableRows['wp_acx_identity_members'] = [
			[
				'identity_uuid' => 'identity-p',
				'cluster_uuid' => 'cluster-primary',
				'attachment_id' => 1,
				'bbox_json' => '[0,0,1,1]',
				'thumb_path' => 'http://example.test/p.jpg',
				'similarity' => '0.9',
				'updated_at' => '2026-05-07 14:11:00',
			],
			[
				'identity_uuid' => 'identity-s',
				'cluster_uuid' => 'cluster-secondary',
				'attachment_id' => 2,
				'bbox_json' => '[0,0,1,1]',
				'thumb_path' => 'http://example.test/s.jpg',
				'similarity' => '0.8',
				'updated_at' => '2026-05-07 15:11:00',
			],
			[
				'identity_uuid' => 'identity-a',
				'cluster_uuid' => 'cluster-ascii',
				'attachment_id' => 3,
				'bbox_json' => '[0,0,1,1]',
				'thumb_path' => 'http://example.test/a.jpg',
				'similarity' => '0.7',
				'updated_at' => '2026-05-07 16:11:00',
			],
		];

		$repository = new RosterEntryProjectionRepository(
			new RosterEntryProjectionSyncStateSpy(
				snapshotVersion: 1,
				lastUpdated: '2026-05-07 18:00:00',
				lastSyncResult: 'ok'
			)
		);

		$data = $repository->list_entries(self::currentTenantId());

		$this->assertCount(2, $data, 'José group + Jose group; accent-distinct under policy');

		$joseGroup = null;
		$asciiGroup = null;
		foreach ($data as $entry) {
			if ('José' === $entry['name'] && 10 === $entry['id']) {
				$joseGroup = $entry;
			}
			if ('Jose' === $entry['name'] && 30 === $entry['id']) {
				$asciiGroup = $entry;
			}
		}
		$this->assertNotNull($joseGroup, 'lowest-id survivor for josé group');
		$this->assertNotNull($asciiGroup, 'Jose remains a separate entry');

		$this->assertSame(10, $joseGroup['id']);
		$this->assertSame('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', $joseGroup['person_uuid']);
		$this->assertSame(2, $joseGroup['cluster_count']);
		$clusterIds = array_map(
			static fn(array $c): string => (string) $c['cluster_id'],
			$joseGroup['clusters']
		);
		sort($clusterIds);
		$this->assertSame(['cluster-primary', 'cluster-secondary'], $clusterIds);

		$queues = $joseGroup['queue_memberships'];
		sort($queues);
		$this->assertSame(['hard-examples', 'singleton-proposals'], $queues);

		$this->assertSame(1, $asciiGroup['cluster_count']);
		$this->assertSame('cluster-ascii', $asciiGroup['clusters'][0]['cluster_id']);
	}

	/**
	 * Pixel-space bbox from the real encode_bbox_json envelope when media_url
	 * comes from the attachment-URL path (scale-1 safe).
	 */
	public function testListEntriesEmitsPixelBboxFromProductionEnvelopeWhenAttachmentResolves(): void
	{
		global $wpdb;

		$normalizer = new class() {
			use NormalizesMemberRows;
		};
		$bbox_json = $normalizer->encode_bbox_json([
			'bbox' => [
				'pixels' => ['x' => 10, 'y' => 20, 'width' => 30, 'height' => 40],
				'normalized' => ['x' => 0.1, 'y' => 0.2, 'width' => 0.3, 'height' => 0.4],
			],
		]);

		$GLOBALS['__ac_attachment_urls'][101] = 'http://example.test/media/101.jpg';

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
				'attachment_id' => 101,
				'bbox_json' => $bbox_json,
				'thumb_path' => 'http://example.test/should-not-use-thumb.jpg',
				'similarity' => '0.98',
				'updated_at' => '2026-05-07 14:31:00',
			],
		];

		$repository = new RosterEntryProjectionRepository(
			new RosterEntryProjectionSyncStateSpy(
				snapshotVersion: 1,
				lastUpdated: '2026-05-07 18:00:00',
				lastSyncResult: 'ok'
			)
		);

		$data = $repository->list_entries(self::currentTenantId());
		$instance = $data[0]['clusters'][0]['instances'][0];

		$this->assertSame('http://example.test/media/101.jpg', $instance['media_url']);
		$this->assertSame(
			['x' => 10, 'y' => 20, 'width' => 30, 'height' => 40],
			$instance['bbox'],
			'Must unwrap pixels from encode_bbox_json envelope, not emit the raw envelope'
		);
		// Discrimination: raw envelope keys must not leak onto the wire.
		$this->assertArrayNotHasKey('pixels', $instance['bbox']);
		$this->assertArrayNotHasKey('normalized', $instance['bbox']);
		$this->assertArrayNotHasKey('coordinate_space', $instance['bbox']);
	}

	public function testListEntriesEmitsNullBboxWhenBboxJsonAbsent(): void
	{
		global $wpdb;

		$GLOBALS['__ac_attachment_urls'][101] = 'http://example.test/media/101.jpg';

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
				'attachment_id' => 101,
				// no bbox_json key
				'thumb_path' => 'http://example.test/thumb.jpg',
				'similarity' => '0.98',
				'updated_at' => '2026-05-07 14:31:00',
			],
		];

		$repository = new RosterEntryProjectionRepository(
			new RosterEntryProjectionSyncStateSpy(
				snapshotVersion: 1,
				lastUpdated: '2026-05-07 18:00:00',
				lastSyncResult: 'ok'
			)
		);

		$data = $repository->list_entries(self::currentTenantId());
		$bbox = $data[0]['clusters'][0]['instances'][0]['bbox'];

		$this->assertNull($bbox, 'Absent bbox_json must stay null, never a zero rect');
	}

	public function testListEntriesEmitsNullBboxWhenBboxJsonIsGarbage(): void
	{
		global $wpdb;

		$GLOBALS['__ac_attachment_urls'][101] = 'http://example.test/media/101.jpg';

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
				'attachment_id' => 101,
				'bbox_json' => 'not-valid-json{{{',
				'thumb_path' => 'http://example.test/thumb.jpg',
				'similarity' => '0.98',
				'updated_at' => '2026-05-07 14:31:00',
			],
		];

		$repository = new RosterEntryProjectionRepository(
			new RosterEntryProjectionSyncStateSpy(
				snapshotVersion: 1,
				lastUpdated: '2026-05-07 18:00:00',
				lastSyncResult: 'ok'
			)
		);

		$data = $repository->list_entries(self::currentTenantId());
		$bbox = $data[0]['clusters'][0]['instances'][0]['bbox'];

		$this->assertNull($bbox, 'Undecodable bbox_json must stay null, never a zero rect');
	}

	public function testListEntriesAcceptsLegacyBarePixelPayloadWithoutPixelsWrapper(): void
	{
		global $wpdb;

		$GLOBALS['__ac_attachment_urls'][101] = 'http://example.test/media/101.jpg';

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
				'attachment_id' => 101,
				// Legacy bare rect — extract_bbox_pixels falls back to $decoded itself.
				'bbox_json' => '{"x":5,"y":6,"width":7,"height":8}',
				'thumb_path' => 'http://example.test/thumb.jpg',
				'similarity' => '0.98',
				'updated_at' => '2026-05-07 14:31:00',
			],
		];

		$repository = new RosterEntryProjectionRepository(
			new RosterEntryProjectionSyncStateSpy(
				snapshotVersion: 1,
				lastUpdated: '2026-05-07 18:00:00',
				lastSyncResult: 'ok'
			)
		);

		$data = $repository->list_entries(self::currentTenantId());
		$bbox = $data[0]['clusters'][0]['instances'][0]['bbox'];

		$this->assertSame(['x' => 5, 'y' => 6, 'width' => 7, 'height' => 8], $bbox);
	}

	/**
	 * Feed one bbox_json envelope through the production projection path and
	 * return the emitted instance bbox.
	 *
	 * @return array<string,int>|null
	 */
	private function projectedInstanceBboxFor(string $bbox_json): ?array
	{
		global $wpdb;

		$GLOBALS['__ac_attachment_urls'][101] = 'http://example.test/media/101.jpg';

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
				'attachment_id' => 101,
				'bbox_json' => $bbox_json,
				'thumb_path' => 'http://example.test/thumb.jpg',
				'similarity' => '0.98',
				'updated_at' => '2026-05-07 14:31:00',
			],
		];

		$repository = new RosterEntryProjectionRepository(
			new RosterEntryProjectionSyncStateSpy(
				snapshotVersion: 1,
				lastUpdated: '2026-05-07 18:00:00',
				lastSyncResult: 'ok'
			)
		);

		$data = $repository->list_entries(self::currentTenantId());

		return $data[0]['clusters'][0]['instances'][0]['bbox'];
	}

	/**
	 * Normalized-only partial envelope (pixels absent) must not become {0,0,0,0}.
	 * A zero-area rect is treated as a valid bbox by consumers and blank-squares.
	 */
	public function testListEntriesEmitsNullBboxForNormalizedOnlyEnvelopeWithoutPixels(): void
	{
		// Real partial envelope: normalized written, pixels key absent.
		$bbox = $this->projectedInstanceBboxFor(
			'{"normalized":{"x":0.1,"y":0.2,"width":0.3,"height":0.4},"coordinate_space":"original_image"}'
		);

		$this->assertNull(
			$bbox,
			'A pixels-less envelope must not become a 0x0 blank-square crop'
		);
	}

	/**
	 * Explicit zero-width pixels rect is not a face — must stay null.
	 */
	public function testListEntriesEmitsNullBboxForZeroWidthPixelsRect(): void
	{
		$bbox = $this->projectedInstanceBboxFor('{"pixels":{"x":5,"y":6,"width":0,"height":40}}');

		$this->assertNull(
			$bbox,
			'Zero-width pixels rect must not become a valid blank-square crop bbox'
		);
	}

	/**
	 * Zero-height with non-zero width. Guards the other axis: a width-only
	 * zero-area check would survive every other case in this suite.
	 */
	public function testListEntriesEmitsNullBboxForZeroHeightPixelsRect(): void
	{
		$bbox = $this->projectedInstanceBboxFor('{"pixels":{"x":5,"y":6,"width":40,"height":0}}');

		$this->assertNull(
			$bbox,
			'Zero-height pixels rect must not become a valid blank-square crop bbox'
		);
	}

	/**
	 * Coordinate-space trap: thumb_path fallback is already a face crop (or not
	 * original_image space). Emitting an original-image bbox would crop a crop.
	 */
	public function testListEntriesNullsBboxOnThumbPathFallbackWhenAttachmentDoesNotResolve(): void
	{
		global $wpdb;

		// attachment_id present but does not resolve (no __ac_attachment_urls entry).
		$normalizer = new class() {
			use NormalizesMemberRows;
		};
		$bbox_json = $normalizer->encode_bbox_json([
			'bbox' => [
				'pixels' => ['x' => 10, 'y' => 20, 'width' => 30, 'height' => 40],
			],
		]);

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
				'bbox_json' => $bbox_json,
				'thumb_path' => 'file:///private/tmp/acx-recognition-blobs/tenant-x/job-y/6731.bin',
				'similarity' => '0.98',
				'updated_at' => '2026-05-07 14:31:00',
			],
		];

		$repository = new RosterEntryProjectionRepository(
			new RosterEntryProjectionSyncStateSpy(
				snapshotVersion: 1,
				lastUpdated: '2026-05-07 18:00:00',
				lastSyncResult: 'ok'
			)
		);

		$data = $repository->list_entries(self::currentTenantId());
		$instance = $data[0]['clusters'][0]['instances'][0];
		$parts = \parse_url($instance['media_url']);

		$this->assertSame('/wp-json/acx/v1/recognition/blobs/job-y/6731', $parts['path']);
		$this->assertNull(
			$instance['bbox'],
			'thumb_path media_url is not original_image space — bbox must be null'
		);
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
