<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Sovereign\Sync\OutboxDispatcher;
use AltContext\Sovereign\Sync\OutboxDrain;
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
