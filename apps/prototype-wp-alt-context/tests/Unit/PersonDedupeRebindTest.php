<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Api\Api;
use AltContext\Api\Services\PersonResolutionService;
use AltContext\Tests\TestCase;
use WP_REST_Request;
use WP_REST_Response;

/**
 * Rebind-on-normalized-match (was: duplicate-key 500 when lookup missed idx_name).
 * Also pins bound person identity on both create and rebind outcomes.
 *
 * Characterization (TEST-03 / DATA-17): pre-Slice-1 commit_roster_cluster looked up
 * by raw name then inserted; a collation-equal collision on UNIQUE idx_name produced
 * wpdb insert failure → WP_Error 500 "Could not create person…". Unit stubs cannot
 * exercise MySQL collation; this suite pins the observable product flip:
 * case/whitespace-normalized match rebinds with zero inserts and returns identity.
 *
 * @covers \AltContext\Api\Api
 * @covers \AltContext\Api\Services\PersonResolutionService
 */
class PersonDedupeRebindTest extends TestCase
{
	private Api $api;

	protected function setUp(): void
	{
		parent::setUp();
		$this->api = new Api();
		$this->setUserCapability('manage_options', true);
	}

	public function testCommitRebindsOnCaseVariantWithoutInsertAndReturnsBoundIdentity(): void
	{
		global $wpdb;

		$existingUuid = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee';
		$wpdb->tableRows['wp_acx_persons'] = [
			[
				'id' => 42,
				'person_uuid' => $existingUuid,
				'name' => 'Ada Lovelace',
				'normalized_name' => PersonResolutionService::normalize_name('Ada Lovelace'),
				'tags' => '[]',
				'tenant_id' => self::currentTenantId(),
			],
		];
		$wpdb->queryResults["SELECT snapshot_version FROM `wp_acx_clusters` WHERE cluster_uuid = 'cluster-rebind' LIMIT 1"] = 3;
		$wpdb->queryResults["SELECT local_revision FROM `wp_acx_clusters` WHERE cluster_uuid = 'cluster-rebind'"] = 2;

		$request = new WP_REST_Request('POST', '/acx/v1/roster/clusters/cluster-rebind/commit');
		$request->set_param('cluster_id', 'cluster-rebind');
		// Case + surrounding whitespace variant — normalizes equal, must rebind not insert.
		$request->set_param('new_entry_name', '  ada lovelace  ');

		$response = $this->api->commit_roster_cluster($request);

		$this->assertInstanceOf(WP_REST_Response::class, $response);
		$data = $response->get_data();
		$this->assertSame('cluster-rebind', $data['cluster_id']);
		$this->assertSame(42, $data['person_id']);
		$this->assertSame($existingUuid, $data['person_uuid']);
		$this->assertSame('Ada Lovelace', $data['person_name']);

		$personInserts = array_values(
			array_filter(
				$wpdb->queries,
				static fn(string $query): bool => str_contains($query, 'INSERT INTO wp_acx_persons')
			)
		);
		$this->assertCount(0, $personInserts, 'rebind must not insert a person row');

		$outboxPersonCreated = array_values(
			array_filter(
				$wpdb->queries,
				static fn(string $query): bool => str_contains($query, "'person_created'")
			)
		);
		$this->assertCount(0, $outboxPersonCreated, 'rebind must not enqueue person_created');

		$lookup = $this->findQueryContaining($wpdb->queries, 'WHERE normalized_name =');
		$this->assertStringContainsString(
			"'" . PersonResolutionService::normalize_name('ada lovelace') . "'",
			$lookup
		);

		$this->assertContains('START TRANSACTION', $wpdb->queries);
		$this->assertContains('COMMIT', $wpdb->queries);
		$this->assertNotContains('ROLLBACK', $wpdb->queries);
	}

	public function testCommitCreateReturnsBoundIdentityForNewPerson(): void
	{
		global $wpdb;

		$wpdb->insert_id = 99;
		$wpdb->queryResults["SELECT snapshot_version FROM `wp_acx_clusters` WHERE cluster_uuid = 'cluster-create' LIMIT 1"] = 1;
		$wpdb->queryResults["SELECT local_revision FROM `wp_acx_clusters` WHERE cluster_uuid = 'cluster-create'"] = 1;

		$request = new WP_REST_Request('POST', '/acx/v1/roster/clusters/cluster-create/commit');
		$request->set_param('cluster_id', 'cluster-create');
		$request->set_param('new_entry_name', 'Grace Hopper');

		$response = $this->api->commit_roster_cluster($request);

		$this->assertInstanceOf(WP_REST_Response::class, $response);
		$data = $response->get_data();
		$this->assertSame('cluster-create', $data['cluster_id']);
		$this->assertSame(99, $data['person_id']);
		$this->assertIsString($data['person_uuid']);
		$this->assertNotSame('', trim((string) $data['person_uuid']));
		$this->assertSame('Grace Hopper', $data['person_name']);

		$personInsert = $this->findQueryContaining($wpdb->queries, 'INSERT INTO wp_acx_persons');
		$this->assertStringContainsString("'Grace Hopper'", $personInsert);
		$this->assertStringContainsString(
			"'" . PersonResolutionService::normalize_name('Grace Hopper') . "'",
			$personInsert
		);
		$this->assertStringContainsString('normalized_name', $personInsert);
	}

	/**
	 * Insert unique-index race in one resolve_or_create call:
	 * first find null → insert false → re-find returns concurrent winner → rebind.
	 */
	public function testInsertFailureWithExistingNormalizedMatchRebinds(): void
	{
		global $wpdb;

		$existingUuid = '11111111-2222-3333-4444-555555555555';
		$wpdb->defaultInsertResult = false;
		$wpdb->tableRows['wp_acx_persons'] = [];
		// Sequence: first find miss, post-insert re-find hit (concurrent winner).
		$wpdb->mockRowSequence = [
			null,
			[
				'id' => 7,
				'person_uuid' => $existingUuid,
				'name' => 'Race Winner',
			],
		];

		$service = new PersonResolutionService();
		$rebound = $service->resolve_or_create('Race Winner', static fn(): bool => true);

		$this->assertIsArray($rebound);
		$this->assertSame('rebound', $rebound['outcome']);
		$this->assertSame(7, $rebound['person_id']);
		$this->assertSame($existingUuid, $rebound['person_uuid']);
		$this->assertSame('Race Winner', $rebound['name']);

		$inserts = array_values(
			array_filter(
				$wpdb->queries,
				static fn(string $q): bool => str_contains($q, 'INSERT INTO wp_acx_persons')
			)
		);
		$this->assertCount(1, $inserts, 'race path must attempt one insert before re-find');
		$lookups = array_values(
			array_filter(
				$wpdb->queries,
				static fn(string $q): bool => str_contains($q, 'WHERE normalized_name =')
			)
		);
		$this->assertCount(2, $lookups, 'first find + post-insert re-find');
	}

	public function testResolveOrCreateIsTransactionAgnostic(): void
	{
		global $wpdb;

		$wpdb->insert_id = 5;
		$service = new PersonResolutionService();
		$result = $service->resolve_or_create(
			'Transaction Free',
			static fn(): bool => true
		);

		$this->assertIsArray($result);
		$this->assertSame('created', $result['outcome']);
		// Service must not open its own transaction (caller owns it).
		$this->assertNotContains('START TRANSACTION', $wpdb->queries);
		$this->assertNotContains('COMMIT', $wpdb->queries);
		$this->assertNotContains('ROLLBACK', $wpdb->queries);
	}

	public function testEnqueueFailureReturnsErrorWithoutNestedTransaction(): void
	{
		global $wpdb;

		$wpdb->insert_id = 6;
		$service = new PersonResolutionService();
		$result = $service->resolve_or_create(
			'Enqueue Fail',
			static fn(): bool => false
		);

		$this->assertInstanceOf(\WP_Error::class, $result);
		$this->assertSame('acx_db_error', $result->get_error_code());
		$this->assertNotContains('START TRANSACTION', $wpdb->queries);
	}

	public function testRollbackLeavesNoCommittedPersonWhenClusterUpdateFails(): void
	{
		global $wpdb;

		$wpdb->insert_id = 88;
		$wpdb->defaultUpdateResult = false;
		$wpdb->queryResults["SELECT snapshot_version FROM `wp_acx_clusters` WHERE cluster_uuid = 'cluster-rollback' LIMIT 1"] = 1;
		$wpdb->queryResults["SELECT local_revision FROM `wp_acx_clusters` WHERE cluster_uuid = 'cluster-rollback'"] = 1;

		$request = new WP_REST_Request('POST', '/acx/v1/roster/clusters/cluster-rollback/commit');
		$request->set_param('cluster_id', 'cluster-rollback');
		$request->set_param('new_entry_name', 'Rollback Person');

		$response = $this->api->commit_roster_cluster($request);

		$this->assertInstanceOf(\WP_Error::class, $response);
		$this->assertContains('START TRANSACTION', $wpdb->queries);
		$this->assertContains('ROLLBACK', $wpdb->queries);
		$this->assertNotContains('COMMIT', $wpdb->queries);
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
