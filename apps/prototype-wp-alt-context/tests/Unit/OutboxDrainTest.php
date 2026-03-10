<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Sovereign\Sync\CrossPlaneSequencer;
use AltContext\Sovereign\Sync\OutboxDispatcher;
use AltContext\Sovereign\Sync\OutboxDrain;
use AltContext\Sovereign\Sync\TopologyCommandRepositoryInterface;
use AltContext\Tests\TestCase;

class OutboxDrainTest extends TestCase
{
	public function testRegisterRegistersHookAndSchedulesWhenPendingExists(): void
	{
		global $wpdb;
		$wpdb->mockVar = '9';

		$drain = new OutboxDrain();
		$drain->register();

		$this->assertArrayHasKey('acx_sync_drain_curation_outbox', $GLOBALS['__ac_actions']);
		$this->assertTrue($this->isHookScheduled('acx_sync_drain_curation_outbox'));
	}

	public function testMaybeScheduleDrainFallsBackToWpCronWhenActionSchedulerEnqueueFails(): void
	{
		$GLOBALS['__ac_action_scheduler_enqueue_result'] = 0;

		OutboxDrain::maybe_schedule_drain();

		$this->assertFalse(as_next_scheduled_action('acx_sync_drain_curation_outbox', [], 'acx-sync'));
		$this->assertNotFalse(wp_next_scheduled('acx_sync_drain_curation_outbox'));
	}

	public function testDrainMarksAcknowledgedOperations(): void
	{
		global $wpdb;
		$wpdb->mockResults = [$this->pendingOperationRow()];

		$dispatcher = new class() extends OutboxDispatcher {
			public function dispatch_batch(array $operations): array {
				return array_fill(0, count($operations), [
					'status' => 'acknowledged',
					'backend_version' => 33,
				]);
			}
		};

		$drain = new OutboxDrain($dispatcher);
		$drain->drain();

		$updateQuery = $this->findQueryContaining($wpdb->queries, 'UPDATE wp_acx_sync_outbox SET');
		$this->assertStringContainsString("status = 'acknowledged'", $updateQuery);
		$this->assertStringContainsString('acknowledged_version = 33', $updateQuery);
	}

	public function testDrainMarksConflictsAndPersistsConflictRows(): void
	{
		global $wpdb;
		$wpdb->mockResults = [$this->pendingOperationRow()];

		$dispatcher = new class() extends OutboxDispatcher {
			public function dispatch_batch(array $operations): array {
				return [[
					'status' => 'conflict',
					'conflict_code' => 'version_conflict',
					'backend_version' => 12,
					'machine_payload' => ['cluster_uuid' => 'cluster-1', 'person_uuid' => 'remote-person'],
				],];
			}
		};

		$drain = new OutboxDrain($dispatcher);
		$drain->drain();

		$conflictInsert = $this->findQueryContaining($wpdb->queries, 'INSERT INTO wp_acx_sync_conflicts');
		$this->assertStringContainsString("'version_conflict'", $conflictInsert);

		$updateQuery = $this->findQueryContaining($wpdb->queries, 'UPDATE wp_acx_sync_outbox SET');
		$this->assertStringContainsString("status = 'conflict'", $updateQuery);
	}

	public function testDrainKeepsRetryableFailuresPendingBeforeMaxAttempts(): void
	{
		global $wpdb;
		$wpdb->mockResults = [$this->pendingOperationRow()];

		$dispatcher = new class() extends OutboxDispatcher {
			public function dispatch_batch(array $operations): array {
				return [[
					'status' => 'failed',
					'error_code' => 'timeout',
					'error_message' => 'gateway timeout',
					'retryable' => true,
				],];
			}
		};

		$drain = new OutboxDrain($dispatcher);
		$drain->drain();

		$updateQuery = $this->findQueryContaining($wpdb->queries, 'UPDATE wp_acx_sync_outbox SET');
		$this->assertStringContainsString("status = 'pending'", $updateQuery);
		$this->assertStringContainsString("last_error_code = 'timeout'", $updateQuery);
	}

	public function testDrainMarksFailedAfterMaxAttempts(): void
	{
		global $wpdb;

		$row = $this->pendingOperationRow();
		$row['attempts'] = 4;
		$wpdb->mockResults = [$row];

		$dispatcher = new class() extends OutboxDispatcher {
			public function dispatch_batch(array $operations): array {
				return [[
					'status' => 'failed',
					'error_code' => 'timeout',
					'error_message' => 'gateway timeout',
					'retryable' => true,
				],];
			}
		};

		$drain = new OutboxDrain($dispatcher);
		$drain->drain();

		$updateQuery = $this->findQueryContaining($wpdb->queries, 'UPDATE wp_acx_sync_outbox SET');
		$this->assertStringContainsString("status = 'failed'", $updateQuery);
	}

	public function testDrainSkipsReplayPlaneTopologyOperationBlockedByEarlierSplitCommand(): void
	{
		global $wpdb;
		$row = $this->pendingOperationRow();
		$row['operation_type'] = 'cluster_merged';
		$row['payload'] = '{"target_cluster_id":"cluster-target"}';
		$row['created_at'] = '2026-03-10 12:00:01';
		$wpdb->mockResults = [$row];
		$wpdb->mockVar = '1';

		$dispatcher = new class() extends OutboxDispatcher {
			public int $dispatchCalls = 0;

			public function dispatch_batch(array $operations): array {
				++$this->dispatchCalls;
				return parent::dispatch_batch($operations);
			}
		};
		$topologyRepository = new class() implements TopologyCommandRepositoryInterface {
			public function enqueue(string $tenant_id, string $command_type, string $entity_key, int $expected_base_version, array $payload, ?string $idempotency_key = null): int|false {
				return false;
			}
			public function find_pending(?string $tenant_id = null, int $limit = 25): array { return []; }
			public function find_reconcilable(?string $tenant_id = null, int $limit = 25): array {
				return [[
					'id' => 3,
					'tenant_id' => 'tenant-test-123',
					'command_type' => 'cluster_split',
					'entity_key' => 'cluster-1',
					'status' => 'pending',
					'payload_json' => ['cluster_id' => 'cluster-1'],
					'result_json' => null,
					'created_at' => '2026-03-10 12:00:00',
				]];
			}
			public function update_status(int $command_id, string $status, ?array $result_payload = null, ?string $backend_command_id = null): bool { return true; }
			public function record_dispatch_result(int $command_id, array $response): bool { return true; }
			public function mark_reconciled(int $command_id, ?array $result_payload = null): bool { return true; }
			public function record_failure(int $command_id, string $status, string $error_code, string $error_message, bool $increment_attempt = true): bool { return true; }
		};

		$drain = new OutboxDrain(
			$dispatcher,
			null,
			null,
			new CrossPlaneSequencer($topologyRepository),
		);
		$drain->drain();

		$this->assertSame(0, $dispatcher->dispatchCalls);
		$this->assertTrue($this->isHookScheduled('acx_sync_drain_curation_outbox'));
		$this->assertSame('', $this->findFirstQueryContaining($wpdb->queries, 'UPDATE wp_acx_sync_outbox SET'));
	}

	/**
	 * @return array<string,mixed>
	 */
	private function pendingOperationRow(): array
	{
		return [
			'id' => 7,
			'tenant_id' => 'tenant-test-123',
			'operation_type' => 'cluster_person_bound',
			'entity_type' => 'cluster',
			'entity_key' => 'cluster-1',
			'idempotency_key' => 'idem-1',
			'expected_base_version' => 11,
			'local_revision' => 4,
			'payload' => '{"cluster_uuid":"cluster-1","person_uuid":"person-1"}',
			'attempts' => 0,
			'created_at' => '2026-03-10 12:00:00',
		];
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

	private function findFirstQueryContaining(array $queries, string $needle): string
	{
		foreach ($queries as $query) {
			if (str_contains($query, $needle)) {
				return $query;
			}
		}

		return '';
	}

	private function isHookScheduled(string $hook): bool
	{
		foreach (array_keys($GLOBALS['__ac_scheduled']) as $key) {
			if (str_starts_with($key, $hook . '::')) {
				return true;
			}
		}

		foreach (array_keys($GLOBALS['__ac_action_scheduler'] ?? []) as $key) {
			if (str_starts_with($key, $hook . '::')) {
				return true;
			}
		}

		return false;
	}
}
