<?php

declare(strict_types=1);

namespace AltContext\Tests\Integration;

use AltContext\Sovereign\Sync\ConflictRepository;
use AltContext\Sovereign\Sync\OutboxDispatcher;
use AltContext\Sovereign\Sync\OutboxDrain;
use AltContext\Sovereign\Sync\OutboxMaintenanceService;
use AltContext\Sovereign\Sync\OutboxQueryRepository;
use AltContext\Support\LifecycleManager;
use Closure;
use PHPUnit\Framework\Attributes\DataProvider;
use PHPUnit\Framework\TestCase;
use ReflectionClass;
use ReflectionMethod;
use RuntimeException;
use Throwable;

/**
 * External GTMBURST-OUTBOX-01 acceptance; intentionally independent of tests/bootstrap.php.
 *
 * GTMBURST_WORDPRESS_SOURCE_PATH points to actual WordPress sources.
 * GTMBURST_OUTBOX_INNODB_FIXTURE points to a private JSON file containing host,
 * database, user (or username), password and optional port (db_host/db_name/db_user/db_password
 * aliases are accepted). Credentials never travel in subprocess arguments/output.
 * The fixture user needs table/constraint DDL and visibility of its own processlist.
 * Discovery needs neither fixture; execution fails, rather than skips, without them.
 */
final class GtmBurstOutboxFenceTest extends TestCase
{
    private const TENANT = 'gtmburst-fence';
    private string $prefix;
    private array $tables = [];
    private array $connections = [];
    private array $workers = [];
    private mixed $originalDb = null;
    private bool $hadOriginalDb = false;
    private bool $savedGlobal = false;
    private \wpdb $ownerA;
    private \wpdb $ownerB;
    private \wpdb $observer;
    private int $id;

    protected function setUp(): void
    {
        parent::setUp();
        self::bootWordPress();
        $this->hadOriginalDb = array_key_exists('wpdb', $GLOBALS);
        $this->originalDb = $GLOBALS['wpdb'] ?? null;
        $this->savedGlobal = true;
        $this->prefix = 'gtmf_' . bin2hex(random_bytes(8)) . '_';
        $this->ownerA = $this->connect();
        $this->ownerB = $this->connect();
        $this->observer = $this->connect();
        $GLOBALS['wpdb'] = $this->ownerA;
        $ids = array_map(static fn(\wpdb $db): int => (int) $db->get_var('SELECT CONNECTION_ID()'), $this->connections);
        self::assertCount(3, array_unique($ids), 'Owners and observer must be independent native connections.');

        $schema = (new LifecycleManager())->build_projection_schema_statements($this->prefix, 'DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci');
        foreach (['acx_sync_outbox', 'acx_sync_conflicts', 'acx_sync_state'] as $suffix) {
            $this->sql($this->ownerA, $schema[$suffix]);
            $this->tables[] = $this->prefix . $suffix;
            // State DDL inherits the session default; explicitly require real transactional tables.
            $this->sql($this->ownerA, 'ALTER TABLE `' . $this->prefix . $suffix . '` ENGINE=InnoDB');
            self::assertSame('InnoDB', $this->ownerA->get_var($this->ownerA->prepare(
                'SELECT ENGINE FROM information_schema.TABLES WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s',
                $this->prefix . $suffix
            )));
        }
        $inserted = $this->ownerA->insert($this->outbox(), [
            'tenant_id' => self::TENANT, 'operation_type' => 'cluster_person_bound',
            'entity_type' => 'cluster', 'entity_key' => 'cluster-1',
            'idempotency_key' => bin2hex(random_bytes(16)),
            'expected_base_version' => 7, 'local_revision' => 2,
            'payload' => '{"label":"local intent"}', 'status' => 'pending',
            'attempts' => 0, 'created_at' => current_time('mysql'),
        ]);
        self::assertSame(1, $inserted, 'Could not create the isolated outbox intent.');
        $this->id = (int) $this->ownerA->insert_id;
        $this->sql($this->ownerA, $this->ownerA->prepare(
            'INSERT INTO %i (stream_name, last_snapshot_version, pending_curation_operations, failed_curation_operations, conflict_count, updated_at) VALUES (%s, 7, 1, 0, 0, %s)',
            $this->prefix . 'acx_sync_state', 'tenant:' . self::TENANT . ':clusters', current_time('mysql')
        ));
    }

    protected function tearDown(): void
    {
        $cleanupFailed = false;
        // Release parent locks before terminating children and touching fixture tables.
        foreach ($this->connections as $db) {
            $db->query('ROLLBACK');
        }
        foreach ($this->workers as $worker) {
            foreach ($worker['pipes'] as $pipe) {
                if (is_resource($pipe)) {
                    fclose($pipe);
                }
            }
            if (is_resource($worker['process'])) {
                if (proc_get_status($worker['process'])['running']) {
                    proc_terminate($worker['process'], 9);
                }
                proc_close($worker['process']);
            }
        }
        if (isset($this->ownerA)) {
            foreach (array_reverse($this->tables) as $table) {
                if ($this->ownerA->query('DROP TABLE `' . $table . '`') === false) {
                    $cleanupFailed = true;
                }
            }
        }
        foreach ($this->connections as $db) {
            $db->close();
        }
        if ($this->savedGlobal) {
            if ($this->hadOriginalDb) {
                $GLOBALS['wpdb'] = $this->originalDb;
            } else {
                unset($GLOBALS['wpdb']);
            }
        }
        parent::tearDown();
        self::assertFalse($cleanupFailed, 'Could not clean up an owned fixture table.');
    }

    public static function responses(): array
    {
        return [
            'success' => [['status' => 'acknowledged', 'backend_version' => 33], [], 'acknowledged'],
            'conflict' => [['status' => 'conflict', 'backend_version' => 33, 'machine_payload' => ['label' => 'remote']], [], 'conflict'],
            'retry' => [['status' => 'failed', 'retryable' => true, 'error_code' => 'unavailable'], [], 'pending'],
            'hard failure' => [['status' => 'failed', 'retryable' => false, 'error_code' => 'invalid'], [], 'failed'],
            'attempt cap' => [['status' => 'failed', 'retryable' => true], ['attempts' => 39], 'failed'],
            'retry window' => [['status' => 'failed', 'retryable' => true], ['first_failed_at' => '2000-01-01 00:00:00'], 'failed'],
        ];
    }

    public static function staleResponses(): array
    {
        $cases = [];
        foreach (self::responses() as $name => [$result, $fields]) {
            foreach ([false, true] as $finishB) {
                $cases[$name . ($finishB ? ' after B completion' : ' while B owns')] = [$result, $fields, $finishB];
            }
        }
        return $cases;
    }

    #[DataProvider('staleResponses')]
    public function testPublicDrainCannotApplyStaleResponse(array $result, array $fields, bool $finishB): void
    {
        $this->patch($fields);
        $before = null;
        $metrics = $this->metrics();
        $called = 0;
        $drain = $this->drain(function (array $operations) use ($result, $finishB, &$before, &$called): array {
            ++$called;
            self::assertCount(1, $operations);
            $a = $operations[0];
            $this->expire();
            $b = $this->reclaimAndClaim($this->ownerB);
            self::assertNotSame($a['claim_token'], $b['claim_token']);
            // Make B's fresh accounting observably different from A's stale snapshot.
            $this->patch(['attempts' => 4, 'first_failed_at' => current_time('mysql')], $this->ownerB);
            $b['attempts'] = 4;
            $b['first_failed_at'] = current_time('mysql');
            if ($finishB) {
                self::assertTrue($this->complete($this->ownerB, $b, ['status' => 'acknowledged', 'backend_version' => 44]));
            }
            $before = $this->row();
            $GLOBALS['wpdb'] = $this->ownerA;
            return [$result];
        });
        $drain->drain();
        self::assertSame(1, $called, 'The real drain must dispatch the claimed operation.');
        self::assertSame($before, $this->row(), 'Stale response must preserve B\'s entire durable row and accounting.');
        self::assertSame([], $this->conflicts(), 'A stale conflict must not reach the conflict inbox.');
        self::assertSame($metrics, $this->metrics(), 'Lost completion must not attribute tenant metrics to stale A.');
        if (!$finishB) {
            $b = $this->row();
            self::assertTrue($this->complete($this->ownerB, $b, ['status' => 'acknowledged', 'backend_version' => 44]));
            self::assertSame(5, (int) $this->row()['attempts'], 'Reclaimed B must remain able to complete with its own accounting.');
        }
    }

    #[DataProvider('responses')]
    public function testHealthyOwnerCompletesThroughPublicDrain(array $result, array $fields, string $status): void
    {
        $this->patch($fields);
        $snapshot = null;
        $drain = $this->drain(static function (array $operations) use ($result, &$snapshot): array {
            $snapshot = $operations[0];
            return [$result];
        });
        $drain->drain();
        $row = $this->row();
        self::assertIsArray($snapshot);
        self::assertSame($status, $row['status']);
        self::assertSame(($fields['attempts'] ?? 0) + 1, (int) $row['attempts']);
        self::assertNull($row['claim_token']);
        self::assertNull($row['claimed_at']);
        self::assertNotNull($row['last_attempted_at']);
        $metrics = $this->metrics();
        self::assertSame($status === 'pending' ? 1 : 0, (int) $metrics['pending_curation_operations']);
        self::assertSame($status === 'failed' ? 1 : 0, (int) $metrics['failed_curation_operations']);
        self::assertSame($status === 'conflict' ? 1 : 0, (int) $metrics['conflict_count']);
        if ($status === 'pending') {
            self::assertGreaterThan($row['last_attempted_at'], $row['next_attempt_at']);
        }
        if ($status === 'acknowledged') {
            self::assertSame(33, (int) $row['acknowledged_version']);
        }
        $conflicts = $this->conflicts();
        self::assertCount($status === 'conflict' ? 1 : 0, $conflicts);
        if ($status === 'conflict') {
            self::assertSame($this->id, (int) $conflicts[0]['outbox_id']);
            self::assertSame('open', $conflicts[0]['resolution_status']);
            self::assertSame(['label' => 'local intent'], json_decode($conflicts[0]['local_payload'], true));
            self::assertSame(33, (int) $conflicts[0]['backend_version']);
        }
        self::assertFalse($this->complete($this->ownerA, $snapshot, $result), 'A completed claim must not count twice.');
        self::assertSame($row, $this->row());
        self::assertSame($conflicts, $this->conflicts());
    }

    public function testConflictInsertionFailureRollsBackOwnedAccountingAndCanRecover(): void
    {
        $this->rejectConflictInsert();
        $claimed = null;
        $beforeMetrics = $this->metrics();
        $drain = $this->drain(function (array $operations) use (&$claimed): array {
            $claimed = $this->row();
            return [['status' => 'conflict', 'backend_version' => 33]];
        });
        $caught = null;
        try {
            $drain->drain();
        } catch (RuntimeException $exception) {
            $caught = $exception;
        }
        self::assertInstanceOf(RuntimeException::class, $caught, 'A real rejected conflict INSERT must be observable.');
        self::assertStringContainsString('owned outbox conflict', $caught->getMessage());
        self::assertIsArray($claimed);
        self::assertSame($claimed, $this->row(), 'Both terminal status and attempt accounting must roll back with the failed INSERT.');
        self::assertSame([], $this->conflicts());
        self::assertSame($beforeMetrics, $this->metrics());
        self::assertSame(0, (int) $this->ownerA->get_var('SELECT @@in_transaction'), 'Failed completion must leave no open transaction.');
        $this->allowConflictInsert();
        $this->expire();
        $drain->drain();
        self::assertSame('conflict', $this->row()['status']);
        self::assertSame(1, (int) $this->row()['attempts']);
        self::assertCount(1, $this->conflicts());
        self::assertSame(1, (int) $this->metrics()['conflict_count']);
    }

    #[DataProvider('responses')]
    public function testReclaimTransactionWinsBeforeOverlappingStaleCompletion(array $result, array $fields, string $unused): void
    {
        $this->patch($fields);
        $a = $this->claim($this->ownerA);
        $this->expire();
        $this->sql($this->ownerB, 'START TRANSACTION');
        $b = $this->reclaimAndClaim($this->ownerB);
        $before = $this->row($this->ownerB);
        // A is still visible to other sessions until B commits its reclaim and new claim.
        self::assertSame($a['claim_token'], $this->row()['claim_token']);
        $worker = $this->startWorker(['action' => 'complete', 'operation' => $a, 'result' => $result]);
        $this->assertBlocked($worker, $this->outbox());
        $this->sql($this->ownerB, 'COMMIT');
        $outcome = $this->finishWorker($worker);
        self::assertFalse($outcome['completed']);
        self::assertSame($before, $this->row());
        self::assertSame([], $this->conflicts());
        self::assertTrue($this->complete($this->ownerB, $b, ['status' => 'acknowledged']));
        self::assertSame((int) $b['attempts'] + 1, (int) $this->row()['attempts']);
    }

    public static function completionOrders(): array
    {
        return ['completion commits' => [false], 'conflict insert rolls back' => [true]];
    }

    #[DataProvider('completionOrders')]
    public function testCompletionTransactionHoldsOffOverlappingReclaim(bool $rejectInsert): void
    {
        $a = $this->claim($this->ownerA);
        $this->expire();
        $before = $this->row();
        if ($rejectInsert) {
            $this->rejectConflictInsert();
        }
        $worker = null;
        $hookCalled = false;
        $repository = new class(function () use (&$worker, &$hookCalled, $before): void {
            $hookCalled = true;
            // Called after the production owned UPDATE, before the real conflict INSERT.
            self::assertSame('conflict', $this->row($this->ownerA)['status']);
            self::assertSame($before, $this->row(), 'Observer must not see the uncommitted completion.');
            self::assertSame([], $this->conflicts());
            $worker = $this->startWorker(['action' => 'reclaim', 'id' => $this->id]);
            $this->assertBlocked($worker, $this->outbox());
        }) extends ConflictRepository {
            public function __construct(private Closure $beforeInsert) { parent::__construct(); }
            public function record_conflict(array $operation, array $result): int|false
            {
                ($this->beforeInsert)();
                return parent::record_conflict($operation, $result);
            }
        };
        $caught = null;
        try {
            self::assertTrue($this->complete($this->ownerA, $a, ['status' => 'conflict', 'backend_version' => 33], $repository));
        } catch (RuntimeException $exception) {
            $caught = $exception;
        }
        self::assertTrue($hookCalled, 'The overlap must occur inside the actual completion transaction.');
        self::assertIsInt($worker);
        $outcome = $this->finishWorker($worker);
        if ($rejectInsert) {
            self::assertInstanceOf(RuntimeException::class, $caught);
            self::assertStringContainsString('owned outbox conflict', $caught->getMessage());
            self::assertSame(1, $outcome['reclaimed']);
            self::assertIsArray($outcome['claimed']);
            self::assertNotSame($a['claim_token'], $outcome['claimed']['claim_token']);
            self::assertSame('in_flight', $this->row()['status']);
            self::assertSame(0, (int) $this->row()['attempts']);
            self::assertSame([], $this->conflicts());
            $this->allowConflictInsert();
            self::assertTrue($this->complete($this->ownerB, $outcome['claimed'], ['status' => 'acknowledged']));
        } else {
            self::assertNull($caught);
            self::assertSame(0, $outcome['reclaimed']);
            self::assertFalse($outcome['claimed']);
            self::assertSame('conflict', $this->row()['status']);
            self::assertSame(1, (int) $this->row()['attempts']);
            self::assertNull($this->row()['claim_token']);
            self::assertCount(1, $this->conflicts());
        }
    }

    private function drain(Closure $dispatch): OutboxDrain
    {
        $GLOBALS['wpdb'] = $this->ownerA;
        $dispatcher = new class($dispatch) extends OutboxDispatcher {
            public function __construct(private Closure $callback) {}
            public function dispatch_batch(array $operations): array { return ($this->callback)($operations); }
        };
        // Only remote responses and unrelated retention work are replaced; all SQL,
        // claim/reclaim/completion, conflict persistence and metric accounting are real.
        $maintenance = new class() extends OutboxMaintenanceService {
            public function purge_terminal_rows(string $tenant_id, ?int $batch_cap = null, ?string $scheduler_mode = null): array|false
            {
                return ['outbox' => 0, 'conflicts' => 0];
            }
        };
        return new OutboxDrain($dispatcher, maintenance_service: $maintenance);
    }

    private function claim(\wpdb $db): array
    {
        $GLOBALS['wpdb'] = $db;
        $operation = (new OutboxQueryRepository())->claim_operation($this->id);
        self::assertIsArray($operation, 'The production repository must acquire an actual durable claim.');
        return $operation;
    }

    private function reclaimAndClaim(\wpdb $db): array
    {
        $GLOBALS['wpdb'] = $db;
        self::assertSame(1, (new OutboxQueryRepository())->reclaim_stale_in_flight_operations(300));
        return $this->claim($db);
    }

    private function complete(\wpdb $db, array $operation, array $result, ?ConflictRepository $repository = null): bool
    {
        $GLOBALS['wpdb'] = $db;
        return self::applyHeldResponse(new OutboxDrain(conflict_repository: $repository), $operation, $result);
    }

    private static function applyHeldResponse(OutboxDrain $drain, array $operation, array $result): bool
    {
        // Replay an already dispatched response without inventing another public claim.
        // Keep the real method/signature so fence-removal mutants exercise the same code.
        return (new ReflectionMethod(OutboxDrain::class, 'apply_result'))->invoke($drain, $operation, $result);
    }

    private function expire(): void
    {
        $this->patch(['claimed_at' => gmdate('Y-m-d H:i:s', time() - 3600)], $this->observer);
    }

    private function patch(array $fields, ?\wpdb $db = null): void
    {
        if ($fields !== []) {
            self::assertNotFalse(($db ?? $this->ownerA)->update($this->outbox(), $fields, ['id' => $this->id]));
        }
    }

    private function row(?\wpdb $db = null): array
    {
        $db ??= $this->observer;
        $row = $db->get_row($db->prepare('SELECT * FROM %i WHERE id = %d', $this->outbox(), $this->id), ARRAY_A);
        self::assertSame('', $db->last_error, 'Fixture outbox read failed.');
        self::assertIsArray($row);
        return $row;
    }

    private function conflicts(): array
    {
        $rows = $this->observer->get_results('SELECT * FROM `' . $this->prefix . 'acx_sync_conflicts` ORDER BY id', ARRAY_A);
        self::assertSame('', $this->observer->last_error, 'Fixture conflict read failed.');
        self::assertIsArray($rows);
        return $rows;
    }

    private function metrics(): array
    {
        $row = $this->observer->get_row($this->observer->prepare(
            'SELECT * FROM %i WHERE stream_name = %s',
            $this->prefix . 'acx_sync_state', 'tenant:' . self::TENANT . ':clusters'
        ), ARRAY_A);
        self::assertSame('', $this->observer->last_error, 'Fixture metrics read failed.');
        self::assertIsArray($row);
        return $row;
    }

    private function outbox(): string { return $this->prefix . 'acx_sync_outbox'; }

    private function rejectConflictInsert(): void
    {
        // Actual MariaDB constraint failure, scoped to this disposable table. No SQL interception.
        $this->sql($this->ownerA, 'ALTER TABLE `' . $this->prefix . 'acx_sync_conflicts` ADD CONSTRAINT reject_owned_conflict CHECK (outbox_id = 0)');
    }

    private function allowConflictInsert(): void
    {
        $this->sql($this->ownerA, 'ALTER TABLE `' . $this->prefix . 'acx_sync_conflicts` DROP CONSTRAINT reject_owned_conflict');
    }

    private function sql(\wpdb $db, string $sql): void
    {
        self::assertNotFalse($db->query($sql), 'Native fixture SQL failed; credentials and server error are intentionally omitted.');
    }

    private function connect(): \wpdb
    {
        $db = self::nativeConnection($this->prefix);
        $this->connections[] = $db;
        return $db;
    }

    private function startWorker(array $request): int
    {
        if (!function_exists('proc_open')) {
            throw new RuntimeException('UNVERIFIED: proc_open is required for actual overlapping InnoDB operations.');
        }
        $request['prefix'] = $this->prefix;
        $code = 'require $argv[1]; require $argv[2]; \\AltContext\\Tests\\Integration\\GtmBurstOutboxFenceTest::runNativeWorker();';
        $process = proc_open([PHP_BINARY, '-d', 'display_errors=0', '-d', 'log_errors=0', '-r', $code,
            dirname(__DIR__, 2) . '/vendor/autoload.php', __FILE__],
            [0 => ['pipe', 'r'], 1 => ['pipe', 'w'], 2 => ['pipe', 'w']], $pipes);
        self::assertIsResource($process, 'Could not start the bounded native PHP worker.');
        $index = count($this->workers);
        $this->workers[$index] = ['process' => $process, 'pipes' => $pipes, 'connection' => null];
        fwrite($pipes[0], json_encode($request, JSON_THROW_ON_ERROR) . "\n");
        $ready = $this->readWorker($index);
        self::assertSame('ready', $ready['phase'] ?? null, 'Native worker fixture could not initialize (details redacted).');
        $this->workers[$index]['connection'] = (int) $ready['connection'];
        self::assertNotContains((int) $ready['connection'], array_map(static fn(\wpdb $db): int => (int) $db->get_var('SELECT CONNECTION_ID()'), $this->connections));
        fwrite($pipes[0], "go\n");
        self::assertSame('executing', $this->readWorker($index)['phase'] ?? null);
        return $index;
    }

    private function readWorker(int $index): array
    {
        $pipe = $this->workers[$index]['pipes'][1];
        $read = [$pipe];
        $write = $except = [];
        self::assertSame(1, stream_select($read, $write, $except, 8), 'Native worker did not respond within its deadline.');
        $line = fgets($pipe);
        self::assertIsString($line, 'Native worker exited without a response (stderr intentionally omitted).');
        $message = json_decode($line, true, 512, JSON_THROW_ON_ERROR);
        self::assertIsArray($message);
        self::assertArrayNotHasKey('error', $message, 'Native worker failed; server details intentionally omitted.');
        return $message;
    }

    private function assertBlocked(int $index, string $table): void
    {
        $connection = $this->workers[$index]['connection'];
        $deadline = microtime(true) + 4;
        $seen = false;
        do {
            // Own-session processlist visibility requires no global PROCESS privilege.
            // A continuously active UPDATE on this tiny, parent-locked table proves
            // the child has reached SQL, rather than merely being slow to start PHP.
            $process = $this->observer->get_row($this->observer->prepare(
                'SELECT COMMAND, STATE, INFO FROM information_schema.PROCESSLIST WHERE ID = %d', $connection
            ), ARRAY_A);
            self::assertSame('', $this->observer->last_error, 'Fixture user must see its own native processlist.');
            $seen = is_array($process) && $process['COMMAND'] === 'Query'
                && stripos((string) $process['INFO'], 'UPDATE') !== false
                && str_contains((string) $process['INFO'], $table);
            if (!$seen) {
                usleep(10000);
            }
        } while (!$seen && microtime(true) < $deadline);
        self::assertTrue($seen, 'Competing production operation never reached the locked fixture UPDATE.');
        $read = [$this->workers[$index]['pipes'][1]];
        $write = $except = [];
        self::assertSame(0, stream_select($read, $write, $except, 0, 250000), 'Competing operation completed while the parent held the InnoDB row lock.');
        $stillActive = $this->observer->get_var($this->observer->prepare(
            'SELECT COMMAND FROM information_schema.PROCESSLIST WHERE ID = %d', $connection
        ));
        self::assertSame('Query', $stillActive, 'The competing SQL must remain active until the parent releases its lock.');
    }

    private function finishWorker(int $index): array
    {
        $response = $this->readWorker($index);
        self::assertSame('done', $response['phase'] ?? null);
        foreach ($this->workers[$index]['pipes'] as $pipe) {
            fclose($pipe);
        }
        $exit = proc_close($this->workers[$index]['process']);
        self::assertSame(0, $exit, 'Native worker did not terminate successfully.');
        return $response;
    }

    /** Entry point for an owned subprocess; no fixture values are emitted. */
    public static function runNativeWorker(): void
    {
        ini_set('display_errors', '0');
        ini_set('log_errors', '0');
        try {
            self::bootWordPress();
            $request = json_decode((string) fgets(STDIN), true, 512, JSON_THROW_ON_ERROR);
            if (!is_array($request) || !preg_match('/^gtmf_[a-f0-9]{16}_$/D', $request['prefix'] ?? '')) {
                throw new RuntimeException('Invalid owned worker request.');
            }
            $db = self::nativeConnection($request['prefix']);
            $GLOBALS['wpdb'] = $db;
            self::emit(['phase' => 'ready', 'connection' => (int) $db->get_var('SELECT CONNECTION_ID()')]);
            if (trim((string) fgets(STDIN)) !== 'go') {
                throw new RuntimeException('Invalid worker handshake.');
            }
            self::emit(['phase' => 'executing']);
            if ($request['action'] === 'complete') {
                $outcome = ['completed' => self::applyHeldResponse(new OutboxDrain(), $request['operation'], $request['result'])];
            } elseif ($request['action'] === 'reclaim') {
                $repository = new OutboxQueryRepository();
                $outcome = ['reclaimed' => $repository->reclaim_stale_in_flight_operations(300),
                    'claimed' => $repository->claim_operation((int) $request['id'])];
            } else {
                throw new RuntimeException('Invalid worker action.');
            }
            $db->close();
            self::emit(['phase' => 'done'] + $outcome);
            exit(0);
        } catch (Throwable $exception) {
            self::emit(['error' => 'Native overlap worker failed; fixture/server details redacted.']);
            exit(1);
        }
    }

    private static function emit(array $message): void
    {
        fwrite(STDOUT, json_encode($message, JSON_THROW_ON_ERROR) . "\n");
        fflush(STDOUT);
    }

    private static function bootWordPress(): void
    {
        if (!extension_loaded('mysqli')) {
            throw new RuntimeException('UNVERIFIED: native mysqli is required; run this test with the protected MariaDB/WordPress fixture.');
        }
        $source = getenv('GTMBURST_WORDPRESS_SOURCE_PATH');
        $root = is_string($source) ? realpath($source) : false;
        if ($root === false || !is_readable($root . '/wp-includes/class-wpdb.php')) {
            throw new RuntimeException('UNVERIFIED: GTMBURST_WORDPRESS_SOURCE_PATH must supply actual WordPress sources.');
        }
        if (!class_exists('wpdb', false)) {
            global $wp_version, $wp_db_version, $tinymce_version, $required_php_version,
                $required_php_extensions, $required_mysql_version, $wp_local_package;
            foreach (['ABSPATH' => $root . '/', 'WPINC' => 'wp-includes', 'WP_DEBUG' => false,
                'WP_DEBUG_DISPLAY' => false, 'WP_DEBUG_LOG' => false, 'WP_SETUP_CONFIG' => true,
                'DB_CHARSET' => 'utf8mb4', 'DB_COLLATE' => ''] as $name => $value) {
                if (!defined($name)) {
                    define($name, $value);
                }
            }
            require_once $root . '/wp-includes/version.php';
            require_once $root . '/wp-includes/compat.php';
            require_once $root . '/wp-includes/load.php';
            require_once $root . '/wp-includes/default-constants.php';
            \wp_initial_constants();
            require_once $root . '/wp-includes/plugin.php';
            require_once $root . '/wp-includes/class-wp-error.php';
            require_once $root . '/wp-includes/functions.php';
            require_once $root . '/wp-includes/formatting.php';
            require_once $root . '/wp-includes/l10n.php';
            require_once $root . '/wp-includes/cron.php';
            require_once $root . '/wp-includes/class-wpdb.php';
        }
        if (realpath((string) (new ReflectionClass('wpdb'))->getFileName()) !== realpath($root . '/wp-includes/class-wpdb.php')) {
            throw new RuntimeException('UNVERIFIED: an existing fake or foreign wpdb bootstrap is forbidden.');
        }
        static $hooksInstalled = false;
        if (!$hooksInstalled) {
            // Real WordPress option/cron hooks isolate the harness from an installed WP
            // site's option tables. They never intercept database queries or SQL results.
            \add_filter('pre_option', static function ($value, $option) {
                return match ($option) {
                    'timezone_string' => 'UTC', 'gmt_offset' => 0, 'cron' => [],
                    default => throw new RuntimeException('Unexpected WordPress option access in isolated integration fixture.'),
                };
            }, 10, 2);
            \add_filter('pre_schedule_event', static fn() => true);
            \add_filter('pre_get_scheduled_event', static fn() => false);
            $hooksInstalled = true;
        }
    }

    private static function nativeConnection(string $prefix): \wpdb
    {
        $file = getenv('GTMBURST_OUTBOX_INNODB_FIXTURE');
        if (!is_string($file) || $file === '' || !is_readable($file)) {
            throw new RuntimeException('UNVERIFIED: GTMBURST_OUTBOX_INNODB_FIXTURE must name the protected readable fixture JSON file.');
        }
        try {
            $fixture = json_decode((string) file_get_contents($file), true, 512, JSON_THROW_ON_ERROR);
            if (!is_array($fixture)) {
                throw new RuntimeException('Invalid fixture object.');
            }
            $host = $fixture['host'] ?? $fixture['db_host'] ?? null;
            $database = $fixture['database'] ?? $fixture['db_name'] ?? null;
            $user = $fixture['user'] ?? $fixture['username'] ?? $fixture['db_user'] ?? null;
            $password = $fixture['password'] ?? $fixture['db_password'] ?? null;
            foreach ([$host, $database, $user, $password] as $value) {
                if (!is_string($value)) {
                    throw new RuntimeException('Invalid fixture fields.');
                }
            }
            if ($host === '' || $database === '' || $user === '') {
                throw new RuntimeException('Empty fixture fields.');
            }
            if (isset($fixture['port'])) {
                $port = filter_var($fixture['port'], FILTER_VALIDATE_INT, ['options' => ['min_range' => 1, 'max_range' => 65535]]);
                if ($port === false) {
                    throw new RuntimeException('Invalid fixture port.');
                }
                $host .= ':' . $port;
            }
            // Suppress native connection diagnostics which may contain fixture values.
            mysqli_report(MYSQLI_REPORT_OFF);
            $db = @new \wpdb($user, $password, $database, $host);
            $db->suppress_errors(true);
            $db->hide_errors();
            if (!$db->ready || !$db->has_cap('identifier_placeholders')) {
                throw new RuntimeException('Native wpdb connection unavailable.');
            }
            $db->set_prefix($prefix);
            if ($db->query('SET SESSION innodb_lock_wait_timeout = 10') === false
                || $db->query('SET SESSION TRANSACTION ISOLATION LEVEL READ COMMITTED') === false) {
                throw new RuntimeException('Could not configure native session.');
            }
            return $db;
        } catch (Throwable $exception) {
            throw new RuntimeException('UNVERIFIED: native fixture connection/configuration failed; credentials and server diagnostics redacted.');
        }
    }
}
