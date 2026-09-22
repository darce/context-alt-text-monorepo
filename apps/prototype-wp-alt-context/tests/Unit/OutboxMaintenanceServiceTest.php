<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Sovereign\Repositories\SyncStateRepository;
use AltContext\Sovereign\Sync\OutboxDispatcher;
use AltContext\Sovereign\Sync\OutboxDrain;
use AltContext\Sovereign\Sync\OutboxMaintenanceService;
use AltContext\Sovereign\Sync\OutboxQueryRepository;
use AltContext\Sovereign\Sync\OutboxStatus;
use AltContext\Tests\TestCase;

class OutboxMaintenanceServiceTest extends TestCase
{
    public function testRetryFailedOperationResetsStateRefreshesMetricsAndSchedulesDrain(): void
    {
        global $wpdb;

        $tenantId = 'tenant-test-123';
        $this->configureSyncMetricQueries($tenantId, [
            'pending' => 1,
            'failed' => 0,
            'conflicts' => 0,
        ]);
        $wpdb->mockRow = array_merge(
            $this->buildOutboxRow(9, $tenantId, 'failed'),
            ['payload' => '{"source":"operator"}']
        );

        $service = new OutboxMaintenanceService();
        $result = $service->retry_failed_operation(9, $tenantId);

        $this->assertTrue($result);
        $updateQuery = $this->findQueryContaining($wpdb->queries, 'UPDATE wp_acx_sync_outbox SET');
        $this->assertStringContainsString("status = 'pending'", $updateQuery);
        $this->assertStringContainsString('attempts = 0', $updateQuery);
        $this->assertStringContainsString('last_error_code = NULL', $updateQuery);
        $this->assertStringContainsString('last_error_retryable = NULL', $updateQuery);

        $syncStateUpdate = $this->findQueryContaining($wpdb->queries, 'UPDATE wp_acx_sync_state SET');
        $this->assertStringContainsString('pending_curation_operations = 1', $syncStateUpdate);
        $this->assertStringContainsString('failed_curation_operations = 0', $syncStateUpdate);
        $this->assertTrue($this->isHookScheduled('acx_sync_drain_curation_outbox'));
    }

    public function testRetryFailedOperationRejectsStaleFingerprintWithoutMutatingNewerFailure(): void
    {
        global $wpdb;

        $tenantId = 'tenant-test-123';
        $staleOperation = array_merge(
            $this->buildOutboxRow(9, $tenantId, 'failed', 5),
            ['payload' => '{"source":"stale"}']
        );
        $currentOperation = array_merge(
            $this->buildOutboxRow(9, $tenantId, 'failed', 6),
            ['payload' => '{"source":"newer"}']
        );
        $wpdb->tableRows['wp_acx_sync_outbox'] = [$currentOperation];

        $repository = new class($staleOperation) extends OutboxQueryRepository {
            /** @var array<string,mixed> */
            private array $operation;

            /** @param array<string,mixed> $operation */
            public function __construct(array $operation)
            {
                $this->operation = $operation;
            }

            public function find_operation_by_id(int $outbox_id, string $tenant_id): ?array
            {
                return $this->operation;
            }
        };

        $service = new OutboxMaintenanceService($repository);

        $this->assertFalse($service->retry_failed_operation(9, $tenantId));
        $this->assertSame(6, $wpdb->tableRows['wp_acx_sync_outbox'][0]['attempts']);
        $this->assertSame('{"source":"newer"}', $wpdb->tableRows['wp_acx_sync_outbox'][0]['payload']);

        $updates = array_values(array_filter(
            $wpdb->queries,
            static fn (string $query): bool => str_starts_with($query, 'UPDATE wp_acx_sync_outbox SET')
        ));
        $this->assertCount(1, $updates);
        // CAS pins the stale snapshot it read, so it matches zero rows against the newer failure.
        $this->assertStringContainsString('AND attempts = 5', $updates[0]);
        $this->assertStringContainsString("AND last_error_code = 'remote_error'", $updates[0]);
    }

    public function testRetryFailedOperationReturnsFalseForMissingRowWithoutUpdate(): void
    {
        $service = new OutboxMaintenanceService();

        $this->assertFalse($service->retry_failed_operation(9, 'tenant-test-123'));
        $this->assertSame([], array_values(array_filter(
            $GLOBALS['wpdb']->queries,
            static fn (string $query): bool => str_starts_with($query, 'UPDATE')
        )));
    }

    public function testRetryFailedOperationReturnsFalseForNonFailedRowWithoutUpdate(): void
    {
        global $wpdb;

        $wpdb->mockRow = $this->buildOutboxRow(9, 'tenant-test-123', 'pending', 1);
        $service = new OutboxMaintenanceService();

        $this->assertFalse($service->retry_failed_operation(9, 'tenant-test-123'));
        $this->assertSame([], array_values(array_filter(
            $wpdb->queries,
            static fn (string $query): bool => str_starts_with($query, 'UPDATE')
        )));
    }

    public function testBulkRetryRequeuesOnlyFailedRowsForTenantWithCasGuard(): void
    {
        // E15-35 Slice 2: one guarded action requeues every selected failed push for the
        // tenant. The CAS is expressed once in the set-based UPDATE, so tenant, failed
        // status, and selected IDs are all checked by the same statement.
        global $wpdb;

        $tenantId = 'tenant-test-123';
        $this->configureSyncMetricQueries($tenantId, [
            'pending' => 2,
            'failed' => 0,
            'conflicts' => 0,
        ]);
        // The wpdb double supplies the repository's selected IDs; the integer query
        // result models two affected rows without relying on the double to interpret
        // CASE/JSON expressions in a raw UPDATE.
        $wpdb->mockResults = [
            ['id' => 1],
            ['id' => 2],
        ];
        $wpdb->defaultQueryResult = 2;

        $service = new OutboxMaintenanceService();
        $this->assertSame(2, $service->retry_failed_operations_bulk($tenantId));

        $selectQuery = $this->findQueryContaining($wpdb->queries, 'SELECT id FROM `wp_acx_sync_outbox`');
        $this->assertStringContainsString("tenant_id = '{$tenantId}'", $selectQuery);
        $this->assertStringContainsString("status = 'failed'", $selectQuery);

        $updates = array_values(array_filter(
            $wpdb->queries,
            static fn (string $query): bool => str_starts_with($query, 'UPDATE `wp_acx_sync_outbox` SET')
        ));
        $this->assertCount(1, $updates);
        $update = $updates[0];
        $this->assertStringContainsString("tenant_id = '{$tenantId}'", $update);
        $this->assertStringContainsString("status = 'failed'", $update);
        $this->assertStringContainsString('id IN (1, 2)', $update);
        $this->assertStringContainsString("payload = JSON_REMOVE(payload, '$.acx_auto_attempts')", $update);
        $this->assertSame([1 => null, 2 => null], $this->parseBulkRetryCase($update));

        $syncStateUpdate = $this->findQueryContaining($wpdb->queries, 'UPDATE wp_acx_sync_state SET');
        $this->assertStringContainsString('pending_curation_operations = 2', $syncStateUpdate);
        $this->assertTrue($this->isHookScheduled('acx_sync_drain_curation_outbox'));
    }

    public function testBulkRetryReturnsCommittedCountWhenMetricsRefreshThrows(): void
    {
        global $wpdb;

        $tenantId = 'tenant-test-123';
        $wpdb->mockResults = [
            ['id' => 1],
            ['id' => 2],
        ];
        $wpdb->defaultQueryResult = 2;
        $metrics = new class() extends SyncStateRepository {
            public function refresh_curation_metrics(string $tenant_id): void
            {
                throw new \RuntimeException('metrics failed');
            }
        };
        $failures = [];
        add_action(
            'acx_sync_outbox_retry_additive_failed',
            static function (string $failedTenantId, string $operation, \Throwable $exception) use (&$failures): void {
                $failures[] = [$failedTenantId, $operation, $exception->getMessage()];
            },
            10,
            3
        );

        $service = new OutboxMaintenanceService(null, $metrics);

        $this->assertSame(2, $service->retry_failed_operations_bulk($tenantId));
        $this->assertSame([
            [$tenantId, 'metrics_refresh', 'metrics failed'],
        ], $failures);
    }

    public function testBulkRetryReturnsCommittedCountWhenDrainSchedulingThrows(): void
    {
        global $wpdb;

        $tenantId = 'tenant-test-123';
        $wpdb->mockResults = [
            ['id' => 1],
            ['id' => 2],
        ];
        $wpdb->defaultQueryResult = 2;
        $metrics = $this->trackingSyncStateRepository();
        add_filter(
            'acx_outbox_action_scheduler_group',
            static function (): string {
                throw new \RuntimeException('drain scheduling failed');
            }
        );
        $failures = [];
        add_action(
            'acx_sync_outbox_retry_additive_failed',
            static function (string $failedTenantId, string $operation, \Throwable $exception) use (&$failures): void {
                $failures[] = [$failedTenantId, $operation, $exception->getMessage()];
            },
            10,
            3
        );

        $service = new OutboxMaintenanceService(null, $metrics);

        $this->assertSame(2, $service->retry_failed_operations_bulk($tenantId));
        $this->assertSame([
            [$tenantId, 'drain_schedule', 'drain scheduling failed'],
        ], $failures);
    }

    public function testBulkRetryReturnsFalseWhenCasUpdateFails(): void
    {
        global $wpdb;

        $tenantId = 'tenant-test-123';
        $wpdb->mockResults = [
            ['id' => 1],
            ['id' => 2],
        ];
        $wpdb->defaultQueryResult = false;
        $failures = [];
        add_action(
            'acx_sync_outbox_retry_additive_failed',
            static function (string $failedTenantId, string $operation, \Throwable $exception) use (&$failures): void {
                $failures[] = [$failedTenantId, $operation, $exception->getMessage()];
            },
            10,
            3
        );

        $service = new OutboxMaintenanceService();

        $this->assertFalse($service->retry_failed_operations_bulk($tenantId));
        $this->assertSame([], $failures);
    }

    public function testBulkRetryPacesRequeueSoOneDrainCycleClaimsFewerThanAllRows(): void
    {
        // E15-35 Slice 2 (PA-05): the incident's thundering herd must not recur — a bulk
        // requeue of N rows seeds a spread next_attempt_at so only the first drain-batch-sized
        // chunk is claimable immediately (claim gate: next_attempt_at IS NULL OR <= now);
        // each later chunk is deferred by one further pacing stride.
        global $wpdb;

        $tenantId = 'tenant-test-123';
        $this->configureSyncMetricQueries($tenantId, [
            'pending' => 5,
            'failed' => 0,
            'conflicts' => 0,
        ]);
        add_filter('acx_outbox_drain_batch_size', static fn (): int => 2);

        $wpdb->mockResults = [
            ['id' => 1],
            ['id' => 2],
            ['id' => 3],
            ['id' => 4],
            ['id' => 5],
        ];
        $wpdb->defaultQueryResult = 5;

        $service = new OutboxMaintenanceService();
        $before = (int) current_time('timestamp');
        $this->assertSame(5, $service->retry_failed_operations_bulk($tenantId));

        $update = $this->findQueryContaining($wpdb->queries, 'UPDATE `wp_acx_sync_outbox` SET');
        $this->assertStringContainsString("tenant_id = '{$tenantId}'", $update);
        $this->assertStringContainsString("status = 'failed'", $update);
        $this->assertStringContainsString('id IN (1, 2, 3, 4, 5)', $update);
        $cases = $this->parseBulkRetryCase($update);

        // First chunk (drain batch size 2) is due immediately.
        $this->assertNull($cases[1]);
        $this->assertNull($cases[2]);

        // Later chunks are strictly in the future — a single drain cycle claims < N.
        $chunkTwo = $this->parseWpTimestamp((string) $cases[3]);
        $chunkThree = $this->parseWpTimestamp((string) $cases[5]);
        $this->assertSame($cases[3], $cases[4]);
        $this->assertGreaterThan($before, $chunkTwo);
        $this->assertGreaterThanOrEqual($before + 60, $chunkTwo);
        $this->assertLessThanOrEqual($before + 62, $chunkTwo);
        $this->assertSame(60, $chunkThree - $chunkTwo);
    }

    public function testBulkRetryInvalidTunableFiltersFallBackToDefaults(): void
    {
        // E15-35 Slice 2 review fix (rg-008, slice-1 convention): broken bulk tunable
        // filters can never shrink the sweep to a single row or collapse the pacing
        // stride — non-positive / non-numeric values fall back to the defaults.
        global $wpdb;

        $tenantId = 'tenant-test-123';
        $this->configureSyncMetricQueries($tenantId, [
            'pending' => 3,
            'failed' => 0,
            'conflicts' => 0,
        ]);
        add_filter('acx_outbox_drain_batch_size', static fn (): int => 1);
        add_filter('acx_outbox_bulk_retry_max_rows', static fn (): bool => false);
        add_filter('acx_outbox_bulk_retry_pacing_stride_seconds', static fn (): float => INF);

        $wpdb->mockResults = [
            ['id' => 1],
            ['id' => 2],
            ['id' => 3],
        ];
        $wpdb->defaultQueryResult = 3;

        $service = new OutboxMaintenanceService();
        $before = (int) current_time('timestamp');
        // Default max rows (1000) sweeps all three rows despite the broken filter.
        $this->assertSame(3, $service->retry_failed_operations_bulk($tenantId));

        // Default stride (60s) despite the INF filter.
        $selectQuery = $this->findQueryContaining($wpdb->queries, 'SELECT id FROM `wp_acx_sync_outbox`');
        $this->assertStringContainsString('LIMIT 1000', $selectQuery);
        $update = $this->findQueryContaining($wpdb->queries, 'UPDATE `wp_acx_sync_outbox` SET');
        $cases = $this->parseBulkRetryCase($update);
        $this->assertNull($cases[1]);
        $chunkTwo = $this->parseWpTimestamp((string) $cases[2]);
        $this->assertGreaterThanOrEqual($before + 60, $chunkTwo);
        $this->assertLessThanOrEqual($before + 62, $chunkTwo);
    }

    public function testBulkRetryGarbageAndZeroTunableFiltersFallBackToDefaults(): void
    {
        // E15-35 Slice 2 review fix (rg-008): non-numeric string and zero values are
        // rejected the same way the slice-1 drain tunables reject them.
        global $wpdb;

        $tenantId = 'tenant-test-123';
        $this->configureSyncMetricQueries($tenantId, [
            'pending' => 2,
            'failed' => 0,
            'conflicts' => 0,
        ]);
        add_filter('acx_outbox_drain_batch_size', static fn (): int => 1);
        add_filter('acx_outbox_bulk_retry_max_rows', static fn (): string => 'garbage');
        add_filter('acx_outbox_bulk_retry_pacing_stride_seconds', static fn (): int => 0);

        $wpdb->mockResults = [
            ['id' => 1],
            ['id' => 2],
        ];
        $wpdb->defaultQueryResult = 2;

        $service = new OutboxMaintenanceService();
        $before = (int) current_time('timestamp');
        $this->assertSame(2, $service->retry_failed_operations_bulk($tenantId));

        $selectQuery = $this->findQueryContaining($wpdb->queries, 'SELECT id FROM `wp_acx_sync_outbox`');
        $this->assertStringContainsString('LIMIT 1000', $selectQuery);
        $update = $this->findQueryContaining($wpdb->queries, 'UPDATE `wp_acx_sync_outbox` SET');
        $cases = $this->parseBulkRetryCase($update);
        $this->assertNull($cases[1]);
        $chunkTwo = $this->parseWpTimestamp((string) $cases[2]);
        $this->assertGreaterThanOrEqual($before + 60, $chunkTwo);
        $this->assertLessThanOrEqual($before + 62, $chunkTwo);
    }

    public function testBulkRetryValidTunableOverridesAreHonored(): void
    {
        // Valid overrides pass through: max rows caps the sweep, stride spreads chunks.
        global $wpdb;

        $tenantId = 'tenant-test-123';
        $this->configureSyncMetricQueries($tenantId, [
            'pending' => 2,
            'failed' => 1,
            'conflicts' => 0,
        ]);
        add_filter('acx_outbox_drain_batch_size', static fn (): int => 1);
        add_filter('acx_outbox_bulk_retry_max_rows', static fn (): int => 2);
        add_filter('acx_outbox_bulk_retry_pacing_stride_seconds', static fn (): int => 120);

        $wpdb->mockResults = [
            ['id' => 1],
            ['id' => 2],
        ];
        $wpdb->defaultQueryResult = 2;

        $service = new OutboxMaintenanceService();
        $before = (int) current_time('timestamp');
        $this->assertSame(2, $service->retry_failed_operations_bulk($tenantId));

        $selectQuery = $this->findQueryContaining($wpdb->queries, 'SELECT id FROM `wp_acx_sync_outbox`');
        $this->assertStringContainsString('LIMIT 2', $selectQuery);
        $update = $this->findQueryContaining($wpdb->queries, 'UPDATE `wp_acx_sync_outbox` SET');
        $this->assertStringContainsString('id IN (1, 2)', $update);
        $cases = $this->parseBulkRetryCase($update);
        // Batch size 1 means exactly one selected ID is immediately due; the second
        // selected ID receives the configured 120-second pacing offset.
        $this->assertSame([1, 2], array_keys($cases));
        $this->assertNull($cases[1]);
        $chunkTwo = $this->parseWpTimestamp((string) $cases[2]);
        $this->assertGreaterThanOrEqual($before + 120, $chunkTwo);
        $this->assertLessThanOrEqual($before + 122, $chunkTwo);
    }

    public function testBulkRetryReturnsZeroAndSkipsSideEffectsWhenNothingFailed(): void
    {
        global $wpdb;

        $tenantId = 'tenant-test-123';
        $wpdb->tableRows['wp_acx_sync_outbox'] = [
            $this->buildOutboxRow(1, $tenantId, 'pending', 1),
        ];

        $service = new OutboxMaintenanceService();
        $this->assertSame(0, $service->retry_failed_operations_bulk($tenantId));

        $updates = array_values(array_filter(
            $wpdb->queries,
            static fn (string $query): bool => str_starts_with($query, 'UPDATE')
        ));
        $this->assertSame([], $updates);
        $this->assertFalse($this->isHookScheduled('acx_sync_drain_curation_outbox'));
    }

    public function testBulkRetryReturnsFalseForBlankTenant(): void
    {
        $service = new OutboxMaintenanceService();
        $this->assertFalse($service->retry_failed_operations_bulk('   '));
    }

    public function testMaybeSchedulePurgeUsesActionSchedulerWhenAvailable(): void
    {
        OutboxMaintenanceService::maybe_schedule_purge();

        $this->assertTrue($this->isHookScheduled('acx_sync_purge_terminal_rows'));
        $this->assertFalse(wp_next_scheduled('acx_sync_purge_terminal_rows', []));
        $this->assertNotFalse($this->actionSchedulerPurgeTimestamp());
        $this->assertGreaterThan(time(), (int) $this->actionSchedulerPurgeTimestamp());
    }

    public function testMaybeSchedulePurgeFallsBackToWpCronWhenActionSchedulerFails(): void
    {
        $GLOBALS['__ac_action_scheduler_enqueue_result'] = 0;

        OutboxMaintenanceService::maybe_schedule_purge();

        $this->assertFalse($this->actionSchedulerPurgeTimestamp());
        $scheduled = wp_next_scheduled('acx_sync_purge_terminal_rows', []);
        $this->assertNotFalse($scheduled, 'Expected the WP-Cron fallback to book the purge.');
        $this->assertGreaterThan(time(), (int) $scheduled);
    }

    public function testMaybeSchedulePurgeDoesNotDuplicateAnExistingActionSchedulerPurge(): void
    {
        wp_schedule_event(time() + 7200, 'daily', 'acx_sync_purge_terminal_rows', []);
        as_schedule_single_action(time() + 120, 'acx_sync_purge_terminal_rows', [], 'acx-sync');
        $existing = $this->actionSchedulerPurgeTimestamp();

        OutboxMaintenanceService::maybe_schedule_purge();

        $this->assertSame($existing, $this->actionSchedulerPurgeTimestamp());
        $this->assertFalse(wp_next_scheduled('acx_sync_purge_terminal_rows', []));
    }

    public function testMaybeSchedulePurgeClearsWpCronWhenActionSchedulerOwnsTheHook(): void
    {
        wp_schedule_event(time() + 7200, 'daily', 'acx_sync_purge_terminal_rows', []);
        $this->assertNotFalse(wp_next_scheduled('acx_sync_purge_terminal_rows', []));

        OutboxMaintenanceService::maybe_schedule_purge();

        $this->assertTrue($this->isHookScheduled('acx_sync_purge_terminal_rows'));
        $this->assertFalse(
            wp_next_scheduled('acx_sync_purge_terminal_rows', []),
            'Action Scheduler ownership must call wp_clear_scheduled_hook for the purge hook.'
        );
        $this->assertNotFalse($this->actionSchedulerPurgeTimestamp());
        $this->assertGreaterThan(time(), (int) $this->actionSchedulerPurgeTimestamp());
    }

    public function testOrphanDiscardRechecksEntityGoneTenantScopedAndWritesDurableAuditRow(): void
    {
        global $wpdb;

        $tenantId = 'tenant-orphan-recheck';
        $otherTenantId = 'tenant-other';
        $wpdb->defaultQueryResult = 0;
        $wpdb->tableRows['wp_acx_sync_outbox'] = [
            $this->buildFailedOrphanOutboxRow(301, $tenantId, 'cluster_not_found', 'cluster', 'cluster-gone'),
        ];
        $wpdb->tableRows['wp_acx_clusters'] = [
            [
                'cluster_uuid' => 'cluster-gone',
                'tenant_id' => $otherTenantId,
            ],
        ];

        $service = new OutboxMaintenanceService(
            null,
            $this->trackingSyncStateRepository(),
            'wp_acx_sync_outbox',
            'wp_acx_sync_conflicts'
        );
        $purged = $service->purge_terminal_rows($tenantId);

        $this->assertSame(1, $purged['orphaned']);
        $this->assertSame(OutboxStatus::DISCARDED, $wpdb->tableRows['wp_acx_sync_outbox'][0]['status']);

        $lockQuery = $this->findQueryContaining($wpdb->queries, 'LIMIT 1 FOR UPDATE');
        $this->assertStringContainsString('FROM `wp_acx_sync_outbox`', $lockQuery);
        $this->assertStringContainsString("tenant_id = '{$tenantId}'", $lockQuery);
        $this->assertStringContainsString('id = 301', $lockQuery);

        $clusterGoneQuery = $this->findQueryContaining($wpdb->queries, 'FROM `wp_acx_clusters`');
        $this->assertStringContainsString("cluster_uuid = 'cluster-gone'", $clusterGoneQuery);
        $this->assertStringContainsString("tenant_id = '{$tenantId}'", $clusterGoneQuery);
        $this->assertStringContainsString('FOR UPDATE', $clusterGoneQuery);

        $auditRows = $this->orphanAuditOutboxRows($wpdb->tableRows['wp_acx_sync_outbox'] ?? []);
        $this->assertCount(1, $auditRows);
        $this->assertSame($tenantId, $auditRows[0]['tenant_id']);
        $this->assertSame('orphan_discard_audit', $auditRows[0]['operation_type']);
        $this->assertSame(OutboxStatus::DISCARDED, $auditRows[0]['status']);
        $this->assertSame('cluster', $auditRows[0]['entity_type']);
        $this->assertSame('cluster-gone', $auditRows[0]['entity_key']);
        $auditPayload = json_decode((string) $auditRows[0]['payload'], true);
        $this->assertIsArray($auditPayload);
        $this->assertSame(301, $auditPayload['outbox_id']);
        $this->assertSame('cluster_not_found', $auditPayload['last_error_code']);
        $this->assertSame('orphaned', $auditPayload['reason']);
        $this->assertSame('cluster', $auditPayload['entity_type']);
        $this->assertSame('cluster-gone', $auditPayload['entity_key']);

        $auditInsert = $this->findQueryContaining($wpdb->queries, 'INSERT INTO wp_acx_sync_outbox');
        $this->assertStringContainsString("'orphan_discard_audit'", $auditInsert);
        $this->assertStringContainsString("'{$tenantId}'", $auditInsert);
        $this->assertContains('COMMIT', $wpdb->queries);

        $orphanAudits = $this->actionsNamed('acx_sync_outbox_orphan_discarded');
        $this->assertCount(1, $orphanAudits);
        $this->assertSame(301, $orphanAudits[0]['args'][0]['outbox_id']);
        $this->assertSame($tenantId, $orphanAudits[0]['args'][0]['tenant_id']);
        $this->assertSame('orphaned', $orphanAudits[0]['args'][0]['reason']);
    }

    public function testOrphanDiscardSkipsWhenLocalEntityStillExistsForTenant(): void
    {
        global $wpdb;

        $tenantId = 'tenant-orphan-still-present';
        $wpdb->defaultQueryResult = 0;
        $wpdb->tableRows['wp_acx_sync_outbox'] = [
            $this->buildFailedOrphanOutboxRow(302, $tenantId, 'cluster_not_found', 'cluster', 'cluster-live'),
        ];
        $wpdb->tableRows['wp_acx_clusters'] = [
            [
                'cluster_uuid' => 'cluster-live',
                'tenant_id' => $tenantId,
            ],
        ];

        $service = new OutboxMaintenanceService(
            null,
            $this->trackingSyncStateRepository(),
            'wp_acx_sync_outbox',
            'wp_acx_sync_conflicts'
        );
        $purged = $service->purge_terminal_rows($tenantId);

        $this->assertSame(0, $purged['orphaned']);
        $this->assertSame(OutboxStatus::FAILED, $wpdb->tableRows['wp_acx_sync_outbox'][0]['status']);
        $this->assertSame([], $this->orphanAuditOutboxRows($wpdb->tableRows['wp_acx_sync_outbox'] ?? []));
        $this->assertSame([], $this->actionsNamed('acx_sync_outbox_orphan_discarded'));
        $this->assertSame([], array_values(array_filter(
            $wpdb->queries,
            static fn (string $query): bool => str_contains($query, "'orphan_discard_audit'")
        )));
    }

    public function testOrphanDiscardAuditInsertFailureRollsBackDiscard(): void
    {
        global $wpdb;

        $tenantId = 'tenant-orphan-audit-fail';
        $wpdb->defaultQueryResult = 0;
        $wpdb->defaultInsertResult = false;
        $wpdb->tableRows['wp_acx_sync_outbox'] = [
            $this->buildFailedOrphanOutboxRow(303, $tenantId, 'http_404', 'cluster', 'cluster-missing'),
        ];

        $service = new OutboxMaintenanceService(
            null,
            $this->trackingSyncStateRepository(),
            'wp_acx_sync_outbox',
            'wp_acx_sync_conflicts'
        );
        $purged = $service->purge_terminal_rows($tenantId);

        $this->assertFalse($purged);
        $this->assertContains('ROLLBACK', $wpdb->queries);
        $this->assertSame([], $this->actionsNamed('acx_sync_outbox_orphan_discarded'));
        $this->assertNotSame([], array_values(array_filter(
            $wpdb->queries,
            static fn (string $query): bool => str_contains($query, "'orphan_discard_audit'")
        )));
    }

    /**
     * @return array<string,mixed>
     */
    private function buildOutboxRow(int $id, string $tenantId, string $status, int $attempts = 5): array
    {
        return [
            'id' => $id,
            'tenant_id' => $tenantId,
            'status' => $status,
            'attempts' => $attempts,
            'last_error_code' => 'failed' === $status ? 'remote_error' : null,
            'last_error_message' => 'failed' === $status ? 'Remote curation replay failed.' : null,
            'last_error_retryable' => 'failed' === $status ? 1 : null,
            'last_attempted_at' => '2026-07-16 01:00:00',
            'first_failed_at' => 'failed' === $status ? '2026-07-16 00:00:00' : null,
            'next_attempt_at' => null,
        ];
    }

    /**
     * Parse the prepared CASE expression used by the set-based bulk requeue.
     *
     * @return array<int,string|null>
     */
    private function parseBulkRetryCase(string $query): array
    {
        $matched = preg_match(
            '/next_attempt_at\s*=\s*CASE\s+id\s+(.*?)\s+ELSE\s+next_attempt_at\s+END/is',
            $query,
            $caseMatch
        );
        $this->assertSame(1, $matched, 'Expected a prepared next_attempt_at CASE expression.');

        $matched = preg_match_all(
            "/WHEN\s+(\d+)\s+THEN\s+(NULL|'[^']*')/i",
            $caseMatch[1],
            $whenMatches,
            PREG_SET_ORDER
        );
        $this->assertIsInt($matched);
        $this->assertGreaterThan(0, $matched);

        $cases = [];
        foreach ($whenMatches as $whenMatch) {
            $value = strtoupper($whenMatch[2]) === 'NULL'
                ? null
                : trim($whenMatch[2], "'");
            $cases[(int) $whenMatch[1]] = $value;
        }

        return $cases;
    }

    private function parseWpTimestamp(string $value): int
    {
        $parsed = \DateTimeImmutable::createFromFormat('Y-m-d H:i:s', $value, new \DateTimeZone('UTC'));
        $this->assertNotFalse($parsed, sprintf('Expected WP-clock datetime, got "%s".', $value));

        return $parsed->getTimestamp();
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

    private function actionSchedulerPurgeTimestamp(): int|false
    {
        foreach ($GLOBALS['__ac_action_scheduler'] ?? [] as $entry) {
            if (is_array($entry) && ($entry['hook'] ?? '') === 'acx_sync_purge_terminal_rows') {
                return (int) $entry['timestamp'];
            }
        }

        return false;
    }

    /**
     * @return array<string,mixed>
     */
    private function buildFailedOrphanOutboxRow(
        int $id,
        string $tenantId,
        string $errorCode,
        string $entityType,
        string $entityKey
    ): array {
        return [
            'id' => $id,
            'tenant_id' => $tenantId,
            'status' => OutboxStatus::FAILED,
            'attempts' => 1,
            'last_error_code' => $errorCode,
            'last_error_message' => 'failed',
            'last_error_retryable' => 0,
            'first_failed_at' => '2026-09-16 00:00:00',
            'last_attempted_at' => '2026-09-16 00:00:00',
            'created_at' => '2026-09-16 00:00:00',
            'payload' => '{}',
            'next_attempt_at' => null,
            'entity_type' => $entityType,
            'entity_key' => $entityKey,
        ];
    }

    private function trackingSyncStateRepository(): SyncStateRepository
    {
        return new class() extends SyncStateRepository {
            public int $refreshCount = 0;
            public ?string $lastTenantId = null;

            public function refresh_curation_metrics(string $tenant_id): void
            {
                ++$this->refreshCount;
                $this->lastTenantId = $tenant_id;
            }
        };
    }

    /**
     * @param array<int,array<string,mixed>> $rows
     * @return array<int,array<string,mixed>>
     */
    private function orphanAuditOutboxRows(array $rows): array
    {
        return array_values(array_filter(
            $rows,
            static fn (array $row): bool => 'orphan_discard_audit' === ($row['operation_type'] ?? '')
        ));
    }

    /**
     * @return array<int,array{hook:string,args:array<int,mixed>}>
     */
    private function actionsNamed(string $hook): array
    {
        $matches = [];
        foreach ($GLOBALS['__ac_do_action_log'] ?? [] as $entry) {
            if (is_array($entry) && ($entry['hook'] ?? '') === $hook) {
                $matches[] = $entry;
            }
        }

        return $matches;
    }
}
