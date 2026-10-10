<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Sovereign\Sync\OutboxDispatcher;
use AltContext\Sovereign\Sync\OutboxDrain;
use AltContext\Sovereign\Sync\OutboxQueryRepository;
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
    private ?array $transaction = null;

    public function update(string $table, array $data, array $where, $format = null, $whereFormat = null)
    {
        if ($this->failure === 'update') {
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
        return parent::get_var($query, $x, $y);
    }

    public function insert(string $table, array $data, $format = null)
    {
        if ($this->failure === 'insert') {
            return false;
        }
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
        if (str_contains($sql, 'DATE_SUB')) {
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
}
