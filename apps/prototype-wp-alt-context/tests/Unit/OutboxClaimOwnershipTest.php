<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Sovereign\Sync\OutboxDispatcher;
use AltContext\Sovereign\Sync\OutboxDrain;
use AltContext\Sovereign\Sync\OutboxQueryRepository;
use AltContext\Sovereign\Sync\OutboxMaintenanceService;
use AltContext\Sovereign\Sync\ConflictRepository;
use AltContext\Support\LifecycleManager;
use AltContext\Tests\TestCase;
use PHPUnit\Framework\Attributes\DataProvider;
use ReflectionMethod;
use RuntimeException;

/** Stateful claim/reclaim interleavings; the shared WP stub does not evaluate lease SQL. */
final class OutboxClaimOwnershipTest extends TestCase
{
    private mixed $originalDb;
    private OwnershipDb $db;
    private OutboxDrain $drain;
    private OutboxQueryRepository $repository;

    protected function setUp(): void
    {
        parent::setUp();
        $this->originalDb = $GLOBALS['wpdb'];
        $this->db = new OwnershipDb();
        // phpcs:ignore WordPress.WP.GlobalVariablesOverride.Prohibited -- Dedicated lane fixture.
        $GLOBALS['wpdb'] = $this->db;
        $GLOBALS['__ac_current_time'] = strtotime('2026-10-10 12:00:00 UTC');
        $this->db->row = [
            'id' => 7, 'tenant_id' => 'tenant-test', 'entity_type' => 'cluster',
            'entity_key' => 'cluster-1', 'operation_type' => 'cluster_person_bound',
            'idempotency_key' => 'idem-1', 'status' => 'pending', 'attempts' => 0,
            'payload' => '{}', 'first_failed_at' => null, 'next_attempt_at' => null,
            'claimed_at' => null, 'claim_token' => null, 'created_at' => current_time('mysql'),
        ];
        $this->repository = new OutboxQueryRepository();
        $this->drain = new OutboxDrain();
    }

    protected function tearDown(): void
    {
        // phpcs:ignore WordPress.WP.GlobalVariablesOverride.Prohibited -- Restore shared fixture.
        $GLOBALS['wpdb'] = $this->originalDb;
        parent::tearDown();
    }

    public static function completions(): array
    {
        return [
            'acknowledgement' => [['status' => 'acknowledged', 'backend_version' => 33], []],
            'conflict' => [['status' => 'conflict'], []],
            'retryable' => [['status' => 'failed', 'retryable' => true], []],
            'terminal' => [['status' => 'failed', 'retryable' => false], []],
            'hard cap' => [['status' => 'failed', 'retryable' => true], ['attempts' => 39]],
            'retry window' => [['status' => 'failed', 'retryable' => true], ['first_failed_at' => '2026-10-08 12:00:00']],
        ];
    }

    #[DataProvider('completions')]
    public function testStaleOwnerCannotCompleteReclaimedRow(array $result, array $oldFields): void
    {
        $this->db->row = array_replace($this->db->row, $oldFields);
        $ownerA = $this->claim();
        $GLOBALS['__ac_current_time'] += 301;
        $this->assertSame(1, $this->repository->reclaim_stale_in_flight_operations(300));
        // Completed retries may have intervened before B's pending-row load.
        $this->db->row['attempts'] = 4;
        $this->db->row['first_failed_at'] = '2026-10-10 12:01:00';
        $ownerB = $this->claim();
        $before = $this->db->row;

        $this->complete($ownerA, $result);
        $this->assertSame($before, $this->db->row, "Stale owner A must not mutate owner B's outbox row.");
        $this->assertSame([], $this->db->conflicts, 'Stale conflict must not create an open conflict record.');
        $this->assertTrue($this->complete($ownerB, ['status' => 'acknowledged']));
        $this->assertSame(5, $this->db->row['attempts']);
        $this->assertNull($this->db->row['claim_token']);
        $this->assertNull($this->db->row['claimed_at']);
        $after = $this->db->row;
        $this->assertFalse($this->complete($ownerB, ['status' => 'acknowledged']));
        $this->assertSame($after, $this->db->row);
    }

    public function testStaleConflictAfterNewOwnerTerminalCreatesNothing(): void
    {
        $ownerA = $this->claim();
        $GLOBALS['__ac_current_time'] += 301;
        $this->repository->reclaim_stale_in_flight_operations(300);
        $ownerB = $this->claim();
        $this->complete($ownerB, ['status' => 'acknowledged']);
        $before = $this->db->row;
        $this->complete($ownerA, ['status' => 'conflict']);
        $this->assertSame([], $this->db->conflicts, 'Stale conflict must not create an open conflict record.');
        $this->assertSame($before, $this->db->row);
    }

    public function testSameSecondReacquireUsesDifferentIdentityAndLegacyNullIsRecoverable(): void
    {
        $this->db->row['status'] = 'in_flight';
        $this->assertSame(1, $this->repository->reclaim_stale_in_flight_operations(300));
        $ownerA = $this->claim();
        // Clock rollback after a short lease can repeat the same second.
        $GLOBALS['__ac_current_time'] += 1;
        $this->assertSame(1, $this->repository->reclaim_stale_in_flight_operations(1));
        $this->assertNull($this->db->row['claim_token']);
        $GLOBALS['__ac_current_time'] -= 1;
        $ownerB = $this->claim();
        $this->assertSame($ownerA['claimed_at'], $ownerB['claimed_at']);
        $this->assertNotEmpty($ownerA['claim_token']);
        $this->assertNotSame($ownerA['claim_token'], $ownerB['claim_token']);
        $before = $this->db->row;
        $this->complete($ownerA, ['status' => 'acknowledged']);
        $this->assertSame($before, $this->db->row);
    }

    public function testMissingIdentityFailsClosed(): void
    {
        $owner = $this->claim();
        unset($owner['claim_token']);
        $before = $this->db->row;
        $this->assertFalse($this->complete($owner, ['status' => 'conflict']));
        $this->assertSame($before, $this->db->row);
        $this->assertSame([], $this->db->conflicts);
    }

    public function testClaimUsesFreshAccountingInsteadOfPreclaimSnapshot(): void
    {
        $loaded = $this->repository->load_pending_operations(25);
        $this->db->row['attempts'] = 6;
        $this->db->row['first_failed_at'] = '2026-10-10 11:59:00';
        $claimed = $this->invoke('claim_operations', $loaded)[0];
        $this->complete($claimed, ['status' => 'failed', 'retryable' => true]);
        $this->assertSame(7, $this->db->row['attempts']);
        $this->assertSame('2026-10-10 11:59:00', $this->db->row['first_failed_at']);
        $this->assertSame('pending', $this->db->row['status']);
        $this->assertGreaterThan(current_time('mysql'), $this->db->row['next_attempt_at']);
    }

    #[DataProvider('completions')]
    public function testCurrentOwnerCompletesEveryBranchExactlyOnce(array $result, array $fields): void
    {
        $this->db->row = array_replace($this->db->row, $fields);
        $owner = $this->claim();
        $this->assertTrue($this->complete($owner, $result));
        $this->assertSame(($fields['attempts'] ?? 0) + 1, $this->db->row['attempts']);
        $expected = $result['status'];
        if ($expected === 'failed' && ($result['retryable'] ?? false) && $fields === []) {
            $expected = 'pending';
        }
        $this->assertSame($expected, $this->db->row['status']);
        $this->assertNull($this->db->row['claim_token']);
        $before = $this->db->row;
        $this->assertFalse($this->complete($owner, $result));
        $this->assertSame($before, $this->db->row);
        $this->assertCount($result['status'] === 'conflict' ? 1 : 0, $this->db->conflicts);
    }

    public function testZeroRowsIsLostOwnershipWhileDatabaseFalseIsAnError(): void
    {
        $owner = $this->claim();
        $this->db->updateOutcome = 0;
        $this->assertFalse($this->complete($owner, ['status' => 'acknowledged']));
        $this->db->updateOutcome = false;
        $this->expectException(RuntimeException::class);
        $this->complete($owner, ['status' => 'acknowledged']);
    }

    public function testClaimDatabaseErrorIsNotClaimContention(): void
    {
        $this->db->updateOutcome = 0;
        $this->assertFalse($this->repository->claim_operation(7));
        $this->db->updateOutcome = false;
        $this->expectException(RuntimeException::class);
        $this->repository->claim_operation(7);
    }

    public function testClaimLostDuringSnapshotReadIsNotDispatched(): void
    {
        $this->db->failure = 'read lost';
        $this->assertSame([], $this->invoke('claim_operations', $this->repository->load_pending_operations(25)));
        $this->assertSame('in_flight', $this->db->row['status']);
        $this->assertSame(0, $this->db->row['attempts']);
    }

    public function testSnapshotReadErrorPreservesClaimForLeaseRecovery(): void
    {
        $this->db->failure = 'read error';
        $caught = null;
        try {
            $this->repository->claim_operation(7);
        } catch (RuntimeException $exception) {
            $caught = $exception;
        }
        $this->assertInstanceOf(RuntimeException::class, $caught);
        $this->assertSame('in_flight', $this->db->row['status']);
        $this->assertNotEmpty($this->db->row['claim_token']);
        $GLOBALS['__ac_current_time'] += 301;
        $this->assertSame(1, $this->repository->reclaim_stale_in_flight_operations(300));
        $this->assertNull($this->db->row['claim_token']);
    }

    public static function conflictFailures(): array
    {
        return ['insert' => ['insert'], 'update' => ['update'], 'start' => ['START TRANSACTION'],
            'commit' => ['COMMIT'], 'outbox engine' => ['engine'], 'conflict engine' => ['conflict engine'],];
    }

    #[DataProvider('conflictFailures')]
    public function testConflictFailurePreservesRecoverableClaim(string $failure): void
    {
        $owner = $this->claim();
        $before = $this->db->row;
        $this->db->failure = $failure;
        $caught = null;
        try {
            $this->complete($owner, ['status' => 'conflict']);
        } catch (RuntimeException $exception) {
            $caught = $exception;
        }
        $this->assertInstanceOf(RuntimeException::class, $caught, 'Conflict persistence errors must be observable.');
        $this->assertSame($before, $this->db->row, 'Failed conflict must roll back the outbox transition.');
        $this->assertSame([], $this->db->conflicts);
    }

    public function testLostCompletionDoesNotAttributeTenantSideEffects(): void
    {
        $owner = $this->claim();
        $this->db->row['claim_token'] = 'new-owner';
        $dispatcher = new class() extends OutboxDispatcher {
            public function dispatch_batch(array $operations): array {
                return [['status' => 'acknowledged']];
            }
        };
        $this->drain = new OutboxDrain($dispatcher);
        $this->assertSame([], $this->invoke('process_operation_batch', [$owner]));
    }

    public function testSchemaDeclaresTokenAndTransactionalConflictTables(): void
    {
        $method = new ReflectionMethod(LifecycleManager::class, 'build_projection_schema_statements');
        $schema = $method->invoke(new LifecycleManager(), 'wp_', '');
        $this->assertStringContainsString('claim_token char(64)', $schema['acx_sync_outbox']);
        $this->assertStringContainsString('ENGINE=InnoDB', $schema['acx_sync_outbox']);
        $this->assertStringContainsString('ENGINE=InnoDB', $schema['acx_sync_conflicts']);
    }

    public function testRepeatedEntityVersionConflictReusesRowAndLinksLatestOperation(): void
    {
        $result = ['status' => 'conflict', 'backend_version' => 33, 'conflict_code' => 'version_conflict'];
        $first = $this->claim();
        $this->assertTrue($this->complete($first, $result));
        $firstRow = $this->db->row;
        $this->db->row = array_replace($first, ['id' => 8, 'status' => 'pending', 'attempts' => 0,
            'payload' => '{"label":"latest"}', 'local_revision' => 2,]);
        $second = $this->claim();
        $this->assertTrue($this->complete($second, $result), 'Duplicate coordinates must not strand the new operation.');
        $this->assertSame('conflict', $this->db->row['status']);
        $this->assertSame('conflict', $firstRow['status']);
        $this->assertCount(1, $this->db->conflicts);
        $this->assertSame(8, (int) $this->db->conflicts[0]['outbox_id']);
        $this->assertSame(2, (int) $this->db->conflicts[0]['local_revision']);
        $this->assertSame('{"label":"latest"}', $this->db->conflicts[0]['local_payload']);

        // A new result at previously resolved coordinates must be visible again.
        $this->db->conflicts[0]['resolution_status'] = 'resolved';
        $this->db->conflicts[0]['resolved_at'] = current_time('mysql');
        $this->db->row = array_replace($second, ['id' => 9, 'status' => 'pending', 'attempts' => 0]);
        $this->assertTrue($this->complete($this->claim(), $result));
        $this->assertCount(1, $this->db->conflicts);
        $this->assertSame(9, (int) $this->db->conflicts[0]['outbox_id']);
        $this->assertSame('open', $this->db->conflicts[0]['resolution_status']);
        $this->assertNull($this->db->conflicts[0]['resolved_at']);
    }

    public static function drainFailures(): array
    {
        return ['claim' => ['claim'], 'snapshot' => ['read error'], 'completion' => ['completion'],
            'conflict' => ['insert'], 'reclaim' => ['reclaim'],];
    }

    public function testConflictReuseRollsBackLinkageAndPayloadWhenCommitFails(): void
    {
        $result = ['status' => 'conflict', 'backend_version' => 33];
        $first = $this->claim();
        $this->complete($first, $result);
        $this->db->row = array_replace($first, ['id' => 8, 'status' => 'pending', 'payload' => '{"label":"new"}']);
        $second = $this->claim();
        $before = [$this->db->row, $this->db->conflicts];
        $this->db->failure = 'COMMIT';
        try {
            $this->complete($second, $result);
            $this->fail('A failed conflict-reuse commit must propagate.');
        } catch (RuntimeException $exception) {
            $this->assertStringContainsString('commit', $exception->getMessage());
        }
        $this->assertSame($before, [$this->db->row, $this->db->conflicts]);
        $this->db->failure = '';
        $this->assertTrue($this->complete($second, $result));
        $this->assertCount(1, $this->db->conflicts);
        $this->assertSame(8, (int) $this->db->conflicts[0]['outbox_id']);
    }

    public function testNoChangeUpsertReturnsExistingConflictIdentity(): void
    {
        $repository = new ConflictRepository();
        $owner = $this->claim();
        $id = $repository->record_conflict($owner, ['status' => 'conflict']);
        $this->assertGreaterThan(0, $id);
        $this->assertSame($id, $repository->record_conflict($owner, ['status' => 'conflict']));
        $this->assertCount(1, $this->db->conflicts);
    }

    public function testExecutingAsyncActionCannotSuppressRecoveryWakeup(): void
    {
        $this->db->failure = 'read error';
        $this->drain->register();
        $key = 'acx_sync_drain_curation_outbox::acx-sync::' . md5(serialize([]));
        $GLOBALS['__ac_action_scheduler'][$key]['timestamp'] = true; // AS reports an in-progress action.
        try {
            $this->drain->drain();
            $this->fail('Snapshot failure must propagate.');
        } catch (RuntimeException $exception) {
            $this->assertStringContainsString('claimed outbox', $exception->getMessage());
        }
        $cron = wp_next_scheduled('acx_sync_drain_curation_outbox', []);
        $this->assertNotFalse($cron, 'Recovery must be queued independently of the in-progress AS action.');
        $this->assertGreaterThanOrEqual(time() + 299, $cron);
    }

    public function testRegistrationRecoversLegacyNullLeaseAndDeduplicatesWakeups(): void
    {
        $this->db->row['status'] = 'in_flight';
        $this->drain->register();
        $wake = wp_next_scheduled('acx_sync_drain_curation_outbox', []);
        $this->assertNotFalse($wake);
        $this->assertLessThanOrEqual(time() + 2, $wake);
        $this->drain->register();
        $this->assertSame($wake, wp_next_scheduled('acx_sync_drain_curation_outbox', []));
        $this->assertCount(1, $GLOBALS['__ac_schedule_single_event_calls']);
    }

    public function testFailedRecoveryReadQueuesFallbackAndPreservesPrimaryError(): void
    {
        $this->db->failure = 'read error';
        $this->db->recoveryReadFails = true;
        try {
            $this->drain->drain();
            $this->fail('Snapshot error must remain observable.');
        } catch (RuntimeException $exception) {
            $this->assertStringContainsString('claimed outbox', $exception->getMessage());
        }
        $this->assertNotFalse(wp_next_scheduled('acx_sync_drain_curation_outbox', []));
        $this->assertSame('acx_outbox_recovery_schedule_failed', $GLOBALS['__ac_do_action_log'][0]['hook']);
    }

    #[DataProvider('drainFailures')]
    public function testDrainFailureSchedulesRecoveryAndRegistrationRestoresLostWakeup(string $failure): void
    {
        $dispatcher = new class() extends OutboxDispatcher {
            public function dispatch_batch(array $operations): array {
                return [['status' => 'conflict']];
            }
        };
        $maintenance = new class() extends OutboxMaintenanceService {
            public function purge_terminal_rows(string $tenant_id, ?int $batch_cap = null, ?string $scheduler_mode = null): array|false {
                return ['outbox' => 0, 'conflicts' => 0];
            }
        };
        $this->drain = new OutboxDrain($dispatcher, maintenance_service: $maintenance);
        if ($failure === 'reclaim') {
            $this->claim();
            $GLOBALS['__ac_current_time'] += 301;
        }
        $this->db->failure = $failure;
        $this->drain->register();
        OutboxDrain::clear_scheduled_drain(); // The single action is consumed before the callback.
        $caught = null;
        try {
            $this->drain->drain();
        } catch (RuntimeException $exception) {
            $caught = $exception;
        }
        $this->assertInstanceOf(RuntimeException::class, $caught, 'Persistence failure must still propagate.');
        $wake = $this->drainWakeup();
        $this->assertNotFalse($wake, 'A failed drain must leave an independently queued recovery wake-up.');
        if ($this->db->row['status'] === 'in_flight' && $failure !== 'reclaim') {
            $this->assertGreaterThanOrEqual(time() + 299, $wake);
            $this->assertLessThanOrEqual(time() + 301, $wake);
        }
        OutboxDrain::clear_scheduled_drain();
        $GLOBALS['__ac_actions'] = []; // Simulate a subsequent request before registering hooks again.
        $this->drain->register();
        $this->assertNotFalse($this->drainWakeup(), 'Registration must also recover queues containing only in-flight rows.');
        $this->db->failure = '';
        $this->db->last_error = '';
        $GLOBALS['__ac_current_time'] += 301;
        OutboxDrain::clear_scheduled_drain(); // Consume the recovery action.
        do_action('acx_sync_drain_curation_outbox');
        $this->assertSame('conflict', $this->db->row['status']);
        $this->assertSame(1, $this->db->row['attempts']);
        $this->assertCount(1, $this->db->conflicts);
    }

    private function drainWakeup(): int|false
    {
        $as = as_next_scheduled_action('acx_sync_drain_curation_outbox', [], 'acx-sync');
        $cron = wp_next_scheduled('acx_sync_drain_curation_outbox', []);
        return $as === false ? $cron : ($cron === false ? $as : min($as, $cron));
    }

    public function testUpgradeConvertsPopulatedLegacyTablesEvenWithPreviousFingerprint(): void
    {
        $db = $this->useLegacySchemaDb();
        $manager = new LifecycleManager();
        $schema = $manager->build_projection_schema_statements('{prefix}', '{charset_collate}');
        ksort($schema);
        $parts = [];
        foreach ($schema as $table => $sql) {
            $parts[] = $table . "\n" . preg_replace('/\s+/', ' ', trim($sql));
        }
        $oldFingerprint = sha1(implode("\n", $parts));
        $this->setOption('acx_version', ACX_VERSION);
        $this->setOption('acx_schema_fingerprint', $oldFingerprint);
        $before = $db->tableRows;
        $manager->maybe_upgrade();
        $this->assertSame(['wp_acx_sync_outbox' => 'InnoDB', 'wp_acx_sync_conflicts' => 'InnoDB'], $db->engines,
            'dbDelta alone cannot convert existing table engines.');
        $this->assertSame($before, $db->tableRows, 'Engine migration must preserve populated rows.');
        $this->assertSame($manager->compute_projection_schema_fingerprint(), get_option('acx_schema_fingerprint'));
        $this->assertNotSame($oldFingerprint, get_option('acx_schema_fingerprint'));
        $this->assertCount(2, $db->engineAlters);
        $manager->maybe_upgrade();
        $this->assertCount(2, $db->engineAlters, 'Completed upgrades should not repeat conversions.');
    }

    public static function migrationFailures(): array
    {
        return ['DDL false' => ['alter'], 'silent DDL no-op' => ['noop'], 'engine probe' => ['probe']];
    }

    #[DataProvider('migrationFailures')]
    public function testEngineMigrationFailureDoesNotStampAndRetries(string $failure): void
    {
        $db = $this->useLegacySchemaDb();
        $db->engineFailure = $failure;
        $this->setOption('acx_schema_fingerprint', 'old');
        $manager = new LifecycleManager();
        $manager->maybe_upgrade();
        $this->assertSame('old', get_option('acx_schema_fingerprint'), 'Unverified engines must not be stamped.');
        $this->assertFalse(get_option('acx_version'));
        $db->engineFailure = '';
        $manager->maybe_upgrade();
        $this->assertSame('InnoDB', $db->engines['wp_acx_sync_outbox']);
        $this->assertSame('InnoDB', $db->engines['wp_acx_sync_conflicts']);
        $this->assertSame($manager->compute_projection_schema_fingerprint(), get_option('acx_schema_fingerprint'));
    }

    private function useLegacySchemaDb(): LegacyOutboxSchemaDb
    {
        $db = new LegacyOutboxSchemaDb();
        $db->defaultQueryResult = 0;
        $db->tableRows = ['wp_acx_sync_outbox' => [$this->db->row],
            'wp_acx_sync_conflicts' => [['id' => 2, 'outbox_id' => 7, 'local_payload' => '{"label":"keep"}']],];
        // phpcs:ignore WordPress.WP.GlobalVariablesOverride.Prohibited -- Lane-local schema fixture.
        $GLOBALS['wpdb'] = $db;
        $this->setOption('acx_label_heal_complete', '1');
        return $db;
    }

    private function claim(): array
    {
        $claimed = $this->invoke('claim_operations', $this->repository->load_pending_operations(25));
        $this->assertCount(1, $claimed);
        return $claimed[0];
    }

    private function complete(array $owner, array $result): mixed
    {
        return $this->invoke('apply_result', $owner, $result);
    }

    private function invoke(string $method, mixed ...$args): mixed
    {
        return (new ReflectionMethod(OutboxDrain::class, $method))->invoke($this->drain, ...$args);
    }
}

/** Evaluates predicates and rollback state, rather than trusting recorded SQL strings. */
final class OwnershipDb extends \WPDBStub
{
    public array $row = [];
    public array $conflicts = [];
    public int|false|null $updateOutcome = null;
    public string $failure = '';
    public bool $recoveryReadFails = false;
    private ?array $transaction = null;

    public function update(string $table, array $data, array $where, $format = null, $whereFormat = null)
    {
        if ($this->failure === 'update' || ($this->failure === 'claim' && ($where['status'] ?? '') === 'pending')
            || ($this->failure === 'completion' && ($where['status'] ?? '') === 'in_flight')) {
            return false;
        }
        if ($this->updateOutcome !== null) {
            return $this->updateOutcome;
        }
        foreach ($where as $key => $value) {
            if (($this->row[$key] ?? null) !== $value) {
                return 0;
            }
        }
        $this->row = array_replace($this->row, $data);
        return 1;
    }

    public function get_results($query, $output = OBJECT)
    {
        return $this->row['status'] === 'pending' ? [$this->row] : [];
    }

    public function get_row($query, $output = OBJECT, $y = 0)
    {
        if ($this->failure === 'read lost') {
            $this->row['claim_token'] = 'new-owner';
            return null;
        }
        if ($this->failure === 'read error') {
            $this->last_error = 'Injected read error';
            return null;
        }
        if (preg_match("/claim_token = '([^']+)'/", $query, $match)
            && $this->row['status'] === 'in_flight' && $this->row['claim_token'] === $match[1]) {
            return $this->row;
        }
        return null;
    }

    public function get_var($query, $x = 0, $y = 0)
    {
        if (str_contains($query, 'information_schema.TABLES')) {
            return $this->failure === 'engine' || ($this->failure === 'conflict engine'
                && str_contains($query, 'acx_sync_conflicts')) ? 'MyISAM' : 'InnoDB';
        }
        if (str_contains($query, "WHERE status = 'pending'")) {
            if ($this->row['status'] !== 'pending') {
                return null;
            }
            return str_contains($query, 'MIN(') ? ($this->row['next_attempt_at'] ?? $this->row['created_at']) : $this->row['id'];
        }
        if (str_contains($query, 'DATE_ADD') && str_contains($query, "WHERE status = 'in_flight'")) {
            if ($this->recoveryReadFails) {
                $this->last_error = 'Injected lease metadata error';
                return null;
            }
            if ($this->row['status'] !== 'in_flight') {
                return null;
            }
            preg_match('/INTERVAL (\d+) SECOND/', $query, $match);
            return $this->row['claimed_at'] === null ? current_time('mysql')
                : gmdate('Y-m-d H:i:s', strtotime($this->row['claimed_at'] . ' UTC') + (int) $match[1]);
        }
        return parent::get_var($query, $x, $y);
    }

    public function insert(string $table, array $data, $format = null)
    {
        if ($table !== 'wp_acx_sync_conflicts') {
            return parent::insert($table, $data, $format);
        }
        if ($this->failure === 'insert') {
            return false;
        }
        foreach ($this->conflicts as $existing) {
            if ($this->sameConflictKey($existing, $data)) {
                return false; // Enforce uq_projection_conflict, unlike the shared stub.
            }
        }
        $data['resolved_at'] = null;
        $this->conflicts[] = $data;
        $this->insert_id = count($this->conflicts);
        return 1;
    }

    public function query($sql)
    {
        $this->queries[] = $sql;
        if ($sql === $this->failure) {
            return false;
        }
        if ($sql === 'START TRANSACTION') {
            $this->transaction = [$this->row, $this->conflicts];
            return 0;
        }
        if ($sql === 'ROLLBACK') {
            if ($this->transaction !== null) {
                [$this->row, $this->conflicts] = $this->transaction;
            }
            $this->transaction = null;
            return 0;
        }
        if ($sql === 'COMMIT') {
            $this->transaction = null;
            return 0;
        }
        if (preg_match('/INSERT INTO .*acx_sync_conflicts.*\(([^)]+)\)\s*VALUES\s*\((.*?)\)\s*ON DUPLICATE KEY UPDATE\s*(.*)/s', $sql, $match)) {
            if ($this->failure === 'insert') {
                return false;
            }
            $columns = array_map('trim', explode(',', $match[1]));
            $values = array_map(static fn ($value) => trim($value) === 'NULL' ? null : stripslashes(trim($value)),
                str_getcsv($match[2], ',', "'", '\\'));
            $data = array_combine($columns, $values);
            foreach ($this->conflicts as $index => $existing) {
                if (!$this->sameConflictKey($existing, $data)) {
                    continue;
                }
                preg_match_all('/(\w+)\s*=\s*VALUES\(\1\)/i', $match[3], $updates);
                foreach ($updates[1] as $column) {
                    $this->conflicts[$index][$column] = $data[$column];
                }
                if (preg_match('/resolved_at\s*=\s*NULL/i', $match[3])) {
                    $this->conflicts[$index]['resolved_at'] = null;
                }
                $this->insert_id = str_contains($match[3], 'LAST_INSERT_ID(id)') ? $index + 1 : 0;
                return $existing === $this->conflicts[$index] ? 0 : 2;
            }
            return $this->insert('wp_acx_sync_conflicts', $data);
        }
        if (str_contains($sql, 'DATE_SUB')) {
            if ($this->failure === 'reclaim') {
                return false;
            }
            preg_match('/INTERVAL (\d+) SECOND/', $sql, $match);
            $cutoff = $GLOBALS['__ac_current_time'] - (int) $match[1];
            if ($this->row['status'] === 'in_flight' && ($this->row['claimed_at'] === null
                || strtotime($this->row['claimed_at'] . ' UTC') <= $cutoff)) {
                $this->row['status'] = 'pending';
                $this->row['claimed_at'] = null;
                if (str_contains($sql, 'claim_token = NULL')) {
                    $this->row['claim_token'] = null;
                }
                return 1;
            }
            return 0;
        }
        // phpcs:ignore WordPress.Security.EscapeOutput.ExceptionNotEscaped -- Database fixture diagnostic, never rendered.
        throw new RuntimeException('Unexpected fixture SQL: ' . $sql);
    }

    private function sameConflictKey(array $a, array $b): bool
    {
        foreach (['tenant_id', 'entity_type', 'entity_key', 'conflict_code', 'backend_version'] as $key) {
            if ((string) ($a[$key] ?? '') !== (string) ($b[$key] ?? '')) {
                return false;
            }
        }
        return true;
    }
}

/** dbDelta updates columns but leaves existing storage engines and rows untouched. */
final class LegacyOutboxSchemaDb extends \WPDBStub
{
    public array $engines = ['wp_acx_sync_outbox' => 'MyISAM', 'wp_acx_sync_conflicts' => 'MyISAM'];
    public array $engineAlters = [];
    public string $engineFailure = '';

    public function get_var($query, $x = 0, $y = 0)
    {
        if (str_contains($query, 'information_schema.TABLES')) {
            if ($this->engineFailure === 'probe') {
                $this->last_error = 'Injected engine metadata error';
                return null;
            }
            foreach ($this->engines as $table => $engine) {
                if (str_contains($query, "'" . $table . "'")) {
                    return $engine;
                }
            }
            return null;
        }
        return parent::get_var($query, $x, $y);
    }

    public function query($sql)
    {
        if (preg_match('/ALTER TABLE `?(\w+)`? ENGINE\s*=\s*InnoDB/i', $sql, $match)) {
            $this->engineAlters[] = $sql;
            if ($this->engineFailure === 'alter' && $match[1] === 'wp_acx_sync_conflicts') {
                return false;
            }
            if ($this->engineFailure !== 'noop') {
                $this->engines[$match[1]] = 'InnoDB';
            }
            return 0;
        }
        return parent::query($sql);
    }
}
