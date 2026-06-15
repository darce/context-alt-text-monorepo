<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Sovereign\Sync\CrossPlaneSequencer;
use AltContext\Sovereign\Sync\OutboxDispatcher;
use AltContext\Sovereign\Sync\OutboxDrain;
use AltContext\Sovereign\Sync\OutboxMaintenanceService;
use AltContext\Sovereign\Sync\OutboxQueryRepository;
use AltContext\Sovereign\Sync\TopologyCommandRepositoryInterface;
use AltContext\Tests\TestCase;
use RuntimeException;

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

		$updateQuery = $this->findOutboxStatusUpdate($wpdb->queries);
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

		$updateQuery = $this->findOutboxStatusUpdate($wpdb->queries);
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

		$updateQuery = $this->findOutboxStatusUpdate($wpdb->queries);
		$this->assertStringContainsString("status = 'pending'", $updateQuery);
		$this->assertStringContainsString("last_error_code = 'timeout'", $updateQuery);
		// CON-3: the retryable/failed terminal write is also guarded on the in_flight claim.
		$this->assertStringContainsString("WHERE id = 7 AND status = 'in_flight'", $updateQuery);
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

		$updateQuery = $this->findOutboxStatusUpdate($wpdb->queries);
		$this->assertStringContainsString("status = 'failed'", $updateQuery);
		$this->assertStringContainsString("WHERE id = 7 AND status = 'in_flight'", $updateQuery);
	}

	public function testDrainClaimsPendingRowAsInFlightBeforeDispatch(): void
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

		// CON-3: claim transitions pending -> in_flight gated on the pending status, so a row
		// already claimed by a peer drain is updated by 0 rows (no double dispatch).
		$claim = $this->findQueryContaining($wpdb->queries, "UPDATE wp_acx_sync_outbox SET status = 'in_flight'");
		$this->assertStringContainsString('claimed_at = ', $claim);
		$this->assertStringContainsString("WHERE id = 7 AND status = 'pending'", $claim);
	}

	public function testDrainApplyResultGuardsTerminalWriteOnInFlightClaim(): void
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

		// CON-3: terminal write only lands while this drain still owns the row (status='in_flight'),
		// so a stale worker's write is a no-op and cannot double-increment attempts.
		$apply = $this->findOutboxStatusUpdate($wpdb->queries);
		$this->assertStringContainsString("status = 'acknowledged'", $apply);
		$this->assertStringContainsString("WHERE id = 7 AND status = 'in_flight'", $apply);
	}

	public function testDrainSkipsDispatchAndApplyWhenClaimIsLostToPeerDrain(): void
	{
		global $wpdb;
		$wpdb->mockResults = [$this->pendingOperationRow()];
		// Simulate a peer drain already owning the row: every claim UPDATE matches 0 rows.
		$wpdb->defaultUpdateResult = 0;

		$dispatcher = new class() extends OutboxDispatcher {
			public int $dispatchCalls = 0;

			public function dispatch_batch(array $operations): array {
				++$this->dispatchCalls;
				return array_fill(0, count($operations), [
					'status' => 'acknowledged',
					'backend_version' => 33,
				]);
			}
		};

		$drain = new OutboxDrain($dispatcher);
		$drain->drain();

		// Claim attempted but lost -> no dispatch, no terminal write (so attempts is not bumped twice).
		$this->assertStringContainsString(
			"UPDATE wp_acx_sync_outbox SET status = 'in_flight'",
			$this->findQueryContaining($wpdb->queries, "UPDATE wp_acx_sync_outbox SET status = 'in_flight'")
		);
		$this->assertSame(0, $dispatcher->dispatchCalls);
		$this->assertSame('', $this->findFirstQueryContaining($wpdb->queries, "SET status = 'acknowledged'"));
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
			public function find_pending(?string $tenant_id = null, int $limit = 25): array {
				return []; }
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
				],];
			}
			public function update_status(int $command_id, string $status, ?array $result_payload = null, ?string $backend_command_id = null): bool {
				return true; }
			public function record_dispatch_result(int $command_id, array $response): bool {
				return true; }
			public function mark_reconciled(int $command_id, ?array $result_payload = null): bool {
				return true; }
			public function record_failure(int $command_id, string $status, string $error_code, string $error_message, bool $increment_attempt = true): bool {
				return true; }
			public function record_reconcile_failure(int $command_id, string $status, string $error_code, string $error_message): bool {
				return true; }
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

	public function testDrainReturnsImmediatelyWhenNoPendingOperationsExist(): void
	{
		global $wpdb;
		$wpdb->mockResults = [];
		$wpdb->mockVar = '0';

		$dispatcher = new class() extends OutboxDispatcher {
			public int $dispatchCalls = 0;

			public function dispatch_batch(array $operations): array {
				++$this->dispatchCalls;
				return [];
			}
		};

		$drain = new OutboxDrain($dispatcher);
		$drain->drain();

		$this->assertSame(0, $dispatcher->dispatchCalls);
		$this->assertFalse($this->isHookScheduled('acx_sync_drain_curation_outbox'));
		$this->assertSame('', $this->findFirstQueryContaining($wpdb->queries, 'UPDATE wp_acx_sync_outbox SET'));
	}

	public function testDrainDispatchesMergeTopologyOperationAndMarksAcknowledged(): void
	{
		global $wpdb;
		$row = $this->pendingOperationRow();
		$row['operation_type'] = 'cluster_merged';
		$row['entity_key'] = 'cluster-source';
		$row['payload'] = '{"target_cluster_id":"cluster-target"}';
		$wpdb->mockResults = [$row];
		$this->setOption('acx_recognition_url', 'http://localhost:8000');
		$this->queueHttpResponse([
			'response' => ['code' => 200, 'message' => 'OK'],
			'body' => wp_json_encode([
				'id' => 'cluster-target',
				'tenant_id' => 'tenant-test-123',
				'label' => 'Target',
				'is_labeled' => true,
				'is_auto_label' => false,
				'identity_count' => 4,
				'backend_version' => 55,
				'representatives' => [],
			]),
		]);

		$drain = new OutboxDrain(new OutboxDispatcher());
		$drain->drain();

		$calls = $this->getHttpCalls();
		$this->assertCount(1, $calls);
		$this->assertStringContainsString('/recognition/clusters/cluster-source/merge', $calls[0]['url']);

		$updateQuery = $this->findOutboxStatusUpdate($wpdb->queries);
		$this->assertStringContainsString("status = 'acknowledged'", $updateQuery);
		$this->assertStringContainsString('acknowledged_version = 55', $updateQuery);
	}

	public function testDrainDispatchesRevertMergeTopologyOperationAndMarksConflict(): void
	{
		global $wpdb;
		$row = $this->pendingOperationRow();
		$row['operation_type'] = 'revert_merge_cluster';
		$row['entity_key'] = 'cluster-target';
		$row['payload'] = '{"target_cluster_id":"cluster-target","desired_source_cluster_id":"cluster-restored","moved_identity_ids":["identity-1"]}';
		$wpdb->mockResults = [$row];
		$this->setOption('acx_recognition_url', 'http://localhost:8000');
		$this->queueHttpResponse([
			'response' => ['code' => 409, 'message' => 'Conflict'],
			'body' => wp_json_encode([
				'conflict_code' => 'cluster_version_conflict',
				'backend_version' => 18,
				'machine_payload' => [
					'entity_type' => 'cluster',
					'entity_key' => 'cluster-target',
					'backend_version' => 18,
				],
			]),
		]);

		$drain = new OutboxDrain(new OutboxDispatcher());
		$drain->drain();

		$calls = $this->getHttpCalls();
		$this->assertCount(1, $calls);
		$this->assertStringContainsString('/recognition/clusters/revert-merge', $calls[0]['url']);

		$conflictInsert = $this->findQueryContaining($wpdb->queries, 'INSERT INTO wp_acx_sync_conflicts');
		$this->assertStringContainsString("'cluster_version_conflict'", $conflictInsert);

		$updateQuery = $this->findOutboxStatusUpdate($wpdb->queries);
		$this->assertStringContainsString("status = 'conflict'", $updateQuery);
	}

	public function testReEnqueueWithCurrentBaseCanPersistMergedValueInPayload(): void
	{
		global $wpdb;
		$wpdb->mockRow = [
			'id' => 51,
			'tenant_id' => 'tenant-test-123',
			'operation_type' => 'cluster_label_updated',
			'entity_type' => 'cluster',
			'entity_key' => 'cluster-51',
			'status' => 'conflict',
			'attempts' => 2,
			'expected_base_version' => 9,
			'local_revision' => 4,
			'payload' => '{"label":"Local Name"}',
			'created_at' => '2026-03-11 10:00:00',
			'last_attempted_at' => null,
			'acknowledged_at' => null,
		];

		$drain = new OutboxDrain();
		$result = $drain->re_enqueue_with_current_base(51, 13, 'tenant-test-123', 'Merged Name');

		$this->assertTrue($result);
		$updateQuery = $this->findOutboxStatusUpdate($wpdb->queries);
		$this->assertStringContainsString("status = 'pending'", $updateQuery);
		$this->assertStringContainsString('expected_base_version = 13', $updateQuery);
		$this->assertStringContainsString('\"merged_value\":\"Merged Name\"', $updateQuery);
		$this->assertStringContainsString('payload =', $updateQuery);
	}

	public function testDrainDispatchesAssignOutlierTopologyOperationAndMarksAcknowledged(): void
	{
		global $wpdb;
		$row = $this->pendingOperationRow();
		$row['operation_type'] = 'assign_outlier_to_cluster';
		$row['entity_key'] = 'cluster-target';
		$row['payload'] = '{"identity_id":"identity-1","similarity":0.42}';
		$wpdb->mockResults = [$row];
		$this->setOption('acx_recognition_url', 'http://localhost:8000');
		$this->queueHttpResponse([
			'response' => ['code' => 200, 'message' => 'OK'],
			'body' => wp_json_encode([
				'id' => 'cluster-target',
				'tenant_id' => 'tenant-test-123',
				'label' => 'Target',
				'is_labeled' => true,
				'is_auto_label' => false,
				'identity_count' => 3,
				'backend_version' => 29,
				'representatives' => [],
			]),
		]);

		$drain = new OutboxDrain(new OutboxDispatcher());
		$drain->drain();

		$calls = $this->getHttpCalls();
		$this->assertCount(1, $calls);
		$this->assertStringContainsString('/recognition/clusters/cluster-target/assign', $calls[0]['url']);

		$updateQuery = $this->findOutboxStatusUpdate($wpdb->queries);
		$this->assertStringContainsString("status = 'acknowledged'", $updateQuery);
		$this->assertStringContainsString('acknowledged_version = 29', $updateQuery);
	}

	public function testDrainDispatchesLabelMutationToCurationSyncAndRefreshesMetrics(): void
	{
		global $wpdb;
		$row = $this->pendingOperationRow();
		$row['operation_type'] = 'cluster_label_updated';
		$row['entity_key'] = 'cluster-label';
		$row['payload'] = '{"cluster_uuid":"cluster-label","label":"Renamed Cluster"}';
		$wpdb->mockResults = [$row];
		$this->setOption('acx_recognition_url', 'http://localhost:8000');
		$this->configureSyncMetricQueries('tenant-test-123', [
			'pending' => 0,
			'failed' => 0,
			'conflicts' => 0,
			'acknowledged_at' => '2026-03-10 14:00:00',
		]);
		$this->queueHttpResponse([
			'response' => ['code' => 200, 'message' => 'OK'],
			'body' => wp_json_encode([
				'status' => 'acknowledged',
				'backend_version' => 61,
			]),
		]);

		$drain = new OutboxDrain(new OutboxDispatcher());
		$drain->drain();

		$calls = $this->getHttpCalls();
		$this->assertCount(1, $calls);
		$this->assertStringContainsString('/roster/curation/sync', $calls[0]['url']);
		$this->assertStringContainsString('"operation_type":"cluster_label_updated"', (string) ($calls[0]['body'] ?? ''));

		$outboxUpdate = $this->findOutboxStatusUpdate($wpdb->queries);
		$this->assertStringContainsString("status = 'acknowledged'", $outboxUpdate);
		$this->assertStringContainsString('acknowledged_version = 61', $outboxUpdate);

		$syncStateUpdate = $this->findQueryContaining($wpdb->queries, 'UPDATE wp_acx_sync_state SET');
		$this->assertStringContainsString('pending_curation_operations = 0', $syncStateUpdate);
		$this->assertStringContainsString('failed_curation_operations = 0', $syncStateUpdate);
		$this->assertStringContainsString('conflict_count = 0', $syncStateUpdate);
		$this->assertStringContainsString("last_curation_acknowledged_at = '2026-03-10 14:00:00'", $syncStateUpdate);
	}

	public function testDrainRecordsConflictForStaleLabelMutationAndRefreshesConflictMetrics(): void
	{
		global $wpdb;
		$row = $this->pendingOperationRow();
		$row['operation_type'] = 'cluster_label_updated';
		$row['entity_key'] = 'cluster-label';
		$row['payload'] = '{"cluster_uuid":"cluster-label","label":"Renamed Cluster"}';
		$wpdb->mockResults = [$row];
		$this->setOption('acx_recognition_url', 'http://localhost:8000');
		$this->configureSyncMetricQueries('tenant-test-123', [
			'pending' => 0,
			'failed' => 0,
			'conflicts' => 1,
			'conflict_at' => '2026-03-10 14:05:00',
		]);
		$this->queueHttpResponse([
			'response' => ['code' => 409, 'message' => 'Conflict'],
			'body' => wp_json_encode([
				'conflict_code' => 'version_conflict',
				'backend_version' => 77,
				'machine_payload' => [
					'cluster_uuid' => 'cluster-label',
					'current_label' => 'Backend Label',
				],
			]),
		]);

		$drain = new OutboxDrain(new OutboxDispatcher());
		$drain->drain();

		$conflictInsert = $this->findQueryContaining($wpdb->queries, 'INSERT INTO wp_acx_sync_conflicts');
		$this->assertStringContainsString("'version_conflict'", $conflictInsert);

		$outboxUpdate = $this->findOutboxStatusUpdate($wpdb->queries);
		$this->assertStringContainsString("status = 'conflict'", $outboxUpdate);

		$syncStateUpdate = $this->findQueryContaining($wpdb->queries, 'UPDATE wp_acx_sync_state SET');
		$this->assertStringContainsString('conflict_count = 1', $syncStateUpdate);
		$this->assertStringContainsString("last_curation_conflict_at = '2026-03-10 14:05:00'", $syncStateUpdate);
	}

	public function testDrainMarksStateOperationFailedAfterRepeatedServerErrorsAndRefreshesFailedMetrics(): void
	{
		global $wpdb;
		$row = $this->pendingOperationRow();
		$row['operation_type'] = 'cluster_label_updated';
		$row['entity_key'] = 'cluster-label';
		$row['payload'] = '{"cluster_uuid":"cluster-label","label":"Renamed Cluster"}';
		$row['attempts'] = 4;
		$wpdb->mockResults = [$row];
		$this->setOption('acx_recognition_url', 'http://localhost:8000');
		$this->configureSyncMetricQueries('tenant-test-123', [
			'pending' => 0,
			'failed' => 1,
			'conflicts' => 0,
			'failed_at' => '2026-03-10 14:10:00',
		]);
		$response = [
			'response' => ['code' => 503, 'message' => 'Unavailable'],
			'body' => wp_json_encode([
				'message' => 'backend unavailable',
			]),
		];
		$this->queueHttpResponse($response);
		$this->queueHttpResponse($response);
		$this->queueHttpResponse($response);

		$drain = new OutboxDrain(new OutboxDispatcher());
		$drain->drain();

		$outboxUpdate = $this->findOutboxStatusUpdate($wpdb->queries);
		$this->assertStringContainsString("status = 'failed'", $outboxUpdate);
		$this->assertStringContainsString("last_error_code = 'remote_error'", $outboxUpdate);

		$syncStateUpdate = $this->findQueryContaining($wpdb->queries, 'UPDATE wp_acx_sync_state SET');
		$this->assertStringContainsString('failed_curation_operations = 1', $syncStateUpdate);
		$this->assertStringContainsString("last_curation_failed_at = '2026-03-10 14:10:00'", $syncStateUpdate);
	}

	public function testFindFailedOperationsReturnsDecodedRowsOrderedByDate(): void
	{
		global $wpdb;

		$tenantId = 'tenant-test-123';
		$rows = [
			[
				'id' => 12,
				'tenant_id' => $tenantId,
				'operation_type' => 'cluster_label_updated',
				'entity_type' => 'cluster',
				'entity_key' => 'cluster-2',
				'status' => 'failed',
				'attempts' => 5,
				'expected_base_version' => 8,
				'local_revision' => 3,
				'last_error_code' => 'dispatch_failed',
				'last_error_message' => 'newer failure',
				'payload' => '{"cluster_uuid":"cluster-2"}',
				'created_at' => '2026-03-10 12:05:00',
				'last_attempted_at' => '2026-03-10 12:06:00',
				'acknowledged_at' => null,
			],
			[
				'id' => 11,
				'tenant_id' => $tenantId,
				'operation_type' => 'cluster_dismissed',
				'entity_type' => 'cluster',
				'entity_key' => 'cluster-1',
				'status' => 'failed',
				'attempts' => 4,
				'expected_base_version' => 7,
				'local_revision' => 2,
				'last_error_code' => 'remote_error',
				'last_error_message' => 'older failure',
				'payload' => '{"cluster_uuid":"cluster-1"}',
				'created_at' => '2026-03-10 12:00:00',
				'last_attempted_at' => '2026-03-10 12:01:00',
				'acknowledged_at' => null,
			],
		];

		$wpdb->mockResults = $rows;

		$drain = new OutboxDrain(new OutboxDispatcher());
		$result = $drain->find_failed_operations($tenantId);

		$this->assertSame([12, 11], array_column($result, 'id'));
		$this->assertSame(['cluster_uuid' => 'cluster-2'], $result[0]['payload']);
		$this->assertSame('dispatch_failed', $result[0]['last_error_code']);
	}

	public function testRetryFailedOperationResetsStateRefreshesMetricsAndSchedulesDrain(): void
	{
		global $wpdb;

		$tenantId = 'tenant-test-123';
		$this->configureSyncMetricQueries($tenantId, [
			'pending' => 1,
			'failed' => 0,
			'conflicts' => 0,
		]);

		$drain = new OutboxDrain(new OutboxDispatcher());
		$result = $drain->retry_failed_operation(9, $tenantId);

		$this->assertTrue($result);
		$updateQuery = $this->findOutboxStatusUpdate($wpdb->queries);
		$this->assertStringContainsString("status = 'pending'", $updateQuery);
		$this->assertStringContainsString('attempts = 0', $updateQuery);
		$this->assertStringContainsString('last_error_code = NULL', $updateQuery);

		$syncStateUpdate = $this->findQueryContaining($wpdb->queries, 'UPDATE wp_acx_sync_state SET');
		$this->assertStringContainsString('pending_curation_operations = 1', $syncStateUpdate);
		$this->assertStringContainsString('failed_curation_operations = 0', $syncStateUpdate);
		$this->assertTrue($this->isHookScheduled('acx_sync_drain_curation_outbox'));
	}

	public function testOutboxDrainDelegatesToExtractedCollaboratorsAndSplitLoopPhases(): void
	{
		$this->assertTrue(class_exists(OutboxQueryRepository::class));
		$this->assertTrue(class_exists(OutboxMaintenanceService::class));

		$privateMethods = array_map(
			static fn (\ReflectionMethod $method): string => $method->getName(),
			(new \ReflectionClass(OutboxDrain::class))->getMethods(\ReflectionMethod::IS_PRIVATE)
		);

		foreach (['process_operation_batch', 'refresh_curation_metrics_for_tenants', 'purge_terminal_rows_for_tenants'] as $expectedMethod) {
			$this->assertContains($expectedMethod, $privateMethods, $expectedMethod);
		}
	}

	public function testPurgeTerminalRowsContinuesAfterTenantThrowable(): void
	{
		$purgeCalls = array();
		$maintenance = new class( $purgeCalls ) extends OutboxMaintenanceService {
			/** @var array<int,string> */
			private array $purgeCalls;

			/** @param array<int,string> $purgeCalls */
			public function __construct( array &$purgeCalls ) {
				$this->purgeCalls = &$purgeCalls;
			}

			public function list_terminal_purge_tenant_ids(): array {
				return array( 'tenant-bad', 'tenant-good' );
			}

			public function purge_terminal_rows( string $tenant_id ): array|false {
				$this->purgeCalls[] = $tenant_id;
				if ( 'tenant-bad' === $tenant_id ) {
					throw new RuntimeException( 'purge failed' );
				}

				return array(
					'outbox' => 1,
					'conflicts' => 0,
				);
			}
		};

		$drain = new OutboxDrain( null, null, null, null, null, null, $maintenance );
		$drain->purge_terminal_rows();

		$this->assertSame( array( 'tenant-bad', 'tenant-good' ), $purgeCalls );
	}

	public function testDrainReschedulesWhenPurgeThrowsForProcessedTenant(): void
	{
		add_filter(
			'acx_outbox_drain_batch_size',
			static fn (): int => 1
		);

		global $wpdb;
		$row = $this->pendingOperationRow();
		$wpdb->mockResults = array( $row );
		$wpdb->mockVar = '8';

		$dispatcher = new class() extends OutboxDispatcher {
			public function dispatch_batch( array $operations ): array {
				return array(
					array(
						'status' => 'acknowledged',
						'backend_version' => 12,
					),
				);
			}
		};

		$maintenance = new class() extends OutboxMaintenanceService {
			public function purge_terminal_rows( string $tenant_id ): array|false {
				throw new RuntimeException( 'purge failed' );
			}
		};

		$drain = new OutboxDrain( $dispatcher, null, null, null, null, null, $maintenance );
		$drain->drain();

		$this->assertTrue( $this->isHookScheduled( 'acx_sync_drain_curation_outbox' ) );
	}

	public function testDrainInvokesTerminalPurgeForProcessedTenants(): void
	{
		global $wpdb;
		$wpdb->mockResults = [$this->pendingOperationRow()];
		$wpdb->mockVar = '1';

		$dispatcher = new class() extends OutboxDispatcher {
			public function dispatch_batch(array $operations): array {
				return [[
					'status' => 'acknowledged',
					'backend_version' => 12,
				],];
			}
		};

		$drain = new OutboxDrain($dispatcher);
		$drain->drain();

		$this->assertNotSame(
			'',
			$this->findFirstQueryContaining($wpdb->queries, 'DELETE FROM `wp_acx_sync_outbox`')
		);
	}

	public function testDrainReschedulesWhenBatchLeavesMorePendingOperations(): void
	{
		add_filter(
			'acx_outbox_drain_batch_size',
			static fn (): int => 1
		);

		global $wpdb;
		$row = $this->pendingOperationRow();
		$wpdb->mockResults = [$row];
		$wpdb->mockVar = '8';

		$dispatcher = new class() extends OutboxDispatcher {
			public function dispatch_batch(array $operations): array {
				return [[
					'status' => 'acknowledged',
					'backend_version' => 33,
				],];
			}
		};

		$drain = new OutboxDrain($dispatcher);
		$drain->drain();

		$this->assertTrue($this->isHookScheduled('acx_sync_drain_curation_outbox'));
	}

	public function testDrainIsolatesRetryableFailureAndContinuesProcessingPeerOperation(): void
	{
		global $wpdb;
		$wpdb->mockResults = [
			$this->pendingOperationRow(['id' => 7, 'idempotency_key' => 'idem-1']),
			$this->pendingOperationRow(['id' => 8, 'idempotency_key' => 'idem-2']),
		];

		$dispatcher = new class() extends OutboxDispatcher {
			public function dispatch_batch(array $operations): array {
				return [
					[
						'status' => 'failed',
						'error_code' => 'timeout',
						'error_message' => 'gateway timeout',
						'retryable' => true,
					],
					[
						'status' => 'acknowledged',
						'backend_version' => 41,
					],
				];
			}
		};

		$drain = new OutboxDrain($dispatcher);
		$drain->drain();

		$pendingUpdate = $this->findFirstQueryContaining($wpdb->queries, "status = 'pending'");
		$acknowledgedUpdate = $this->findFirstQueryContaining($wpdb->queries, "status = 'acknowledged'");
		$this->assertNotSame('', $pendingUpdate);
		$this->assertNotSame('', $acknowledgedUpdate);
	}

	public function testDiscardOperationMarksDiscardedAndRefreshesMetrics(): void
	{
		global $wpdb;

		$tenantId = 'tenant-test-123';
		$operationId = 15;
		$this->configureSyncMetricQueries($tenantId, [
			'pending' => 0,
			'failed' => 0,
			'conflicts' => 0,
		]);
		$wpdb->mockRow = [
			'id' => $operationId,
			'tenant_id' => $tenantId,
			'operation_type' => 'cluster_label_updated',
			'entity_type' => 'cluster',
			'entity_key' => 'cluster-1',
			'status' => 'failed',
			'attempts' => 5,
			'expected_base_version' => 8,
			'local_revision' => 3,
			'last_error_code' => 'dispatch_failed',
			'last_error_message' => 'dead letter',
			'payload' => '{"cluster_uuid":"cluster-1"}',
			'created_at' => '2026-03-10 12:00:00',
			'last_attempted_at' => '2026-03-10 12:05:00',
			'acknowledged_at' => null,
		];
		$wpdb->mockResults = [];

		$drain = new OutboxDrain(new OutboxDispatcher());
		$result = $drain->discard_operation($operationId, $tenantId);

		$this->assertTrue($result);
		$updateQuery = $this->findOutboxStatusUpdate($wpdb->queries);
		$this->assertStringContainsString("status = 'discarded'", $updateQuery);

		$syncStateUpdate = $this->findQueryContaining($wpdb->queries, 'UPDATE wp_acx_sync_state SET');
		$this->assertStringContainsString('failed_curation_operations = 0', $syncStateUpdate);
	}

	/**
	 * @param array<string,mixed> $overrides
	 * @return array<string,mixed>
	 */
	private function pendingOperationRow(array $overrides = []): array
	{
		return array_merge([
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
		], $overrides);
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

	/**
	 * First outbox UPDATE that is not the CON-3 row-claim (claim sets status='in_flight').
	 *
	 * @param array<int,string> $queries
	 */
	private function findOutboxStatusUpdate(array $queries): string
	{
		foreach ($queries as $query) {
			if (! str_contains($query, 'UPDATE wp_acx_sync_outbox SET')) {
				continue;
			}
			if (str_contains($query, "SET status = 'in_flight'")) {
				continue;
			}

			return $query;
		}

		$this->fail('Unable to find a non-claim outbox status UPDATE.');
	}

	/**
	 * @param array<string,int|string|null> $overrides
	 */
	private function configureSyncMetricQueries(string $tenantId, array $overrides = []): void
	{
		global $wpdb;

		$wpdb->mockRow = [
			'last_curation_acknowledged_at' => null,
			'last_curation_conflict_at' => null,
			'last_curation_failed_at' => null,
		];

		$pending = (int) ($overrides['pending'] ?? 0);
		$failed = (int) ($overrides['failed'] ?? 0);
		$conflicts = (int) ($overrides['conflicts'] ?? 0);
		$acknowledgedAt = (string) ($overrides['acknowledged_at'] ?? '');
		$conflictAt = (string) ($overrides['conflict_at'] ?? '');
		$failedAt = (string) ($overrides['failed_at'] ?? '');

		$wpdb->queryResults[$wpdb->prepare(
			'SELECT COUNT(*) FROM %i WHERE tenant_id = %s AND status = %s',
			'wp_acx_sync_outbox',
			$tenantId,
			'pending'
		)] = $pending;
		$wpdb->queryResults[$wpdb->prepare(
			'SELECT COUNT(*) FROM %i WHERE tenant_id = %s AND status = %s',
			'wp_acx_sync_outbox',
			$tenantId,
			'failed'
		)] = $failed;
		$wpdb->queryResults[$wpdb->prepare(
			'SELECT COUNT(*) FROM %i WHERE tenant_id = %s AND resolution_status = %s',
			'wp_acx_sync_conflicts',
			$tenantId,
			'open'
		)] = $conflicts;
		$wpdb->queryResults[$wpdb->prepare(
			'SELECT MAX(acknowledged_at) FROM %i WHERE tenant_id = %s AND status = %s',
			'wp_acx_sync_outbox',
			$tenantId,
			'acknowledged'
		)] = $acknowledgedAt;
		$wpdb->queryResults[$wpdb->prepare(
			'SELECT MAX(created_at) FROM %i WHERE tenant_id = %s AND resolution_status = %s',
			'wp_acx_sync_conflicts',
			$tenantId,
			'open'
		)] = $conflictAt;
		$wpdb->queryResults[$wpdb->prepare(
			'SELECT MAX(last_attempted_at) FROM %i WHERE tenant_id = %s AND status = %s',
			'wp_acx_sync_outbox',
			$tenantId,
			'failed'
		)] = $failedAt;
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
