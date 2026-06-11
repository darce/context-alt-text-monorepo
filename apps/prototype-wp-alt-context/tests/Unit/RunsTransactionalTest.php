<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Support\RunsTransactional;
use AltContext\Tests\TestCase;
use RuntimeException;
use WP_Error;

/**
 * @covers \AltContext\Support\RunsTransactional
 */
class RunsTransactionalTest extends TestCase
{
    private object $subject;

    protected function setUp(): void
    {
        parent::setUp();

        $this->subject = new class() {
            use RunsTransactional;

            public function invoke(callable $operation, string $start_error = 'Could not start local transaction.', string $commit_error = 'Could not commit local transaction.'): mixed
            {
                return $this->run_transactional($operation, $start_error, $commit_error);
            }
        };
    }

    public function testCommitPathReturnsCallableResult(): void
    {
        global $wpdb;

        $result = $this->subject->invoke(static fn () => array('ok' => true));

        $this->assertSame(array('ok' => true), $result);
        $this->assertSame(array('START TRANSACTION', 'COMMIT'), $wpdb->queries);
        $this->assertNotContains('ROLLBACK', $wpdb->queries);
    }

    public function testCallableWpErrorPathRollsBackAndReturnsSameInstance(): void
    {
        global $wpdb;
        $error = new WP_Error('enqueue_failed', 'Could not queue replay operation.', array('status' => 500));

        $result = $this->subject->invoke(static fn () => $error);

        $this->assertSame($error, $result);
        $this->assertSame(array('START TRANSACTION', 'ROLLBACK'), $wpdb->queries);
        $this->assertNotContains('COMMIT', $wpdb->queries);
    }

    public function testThrowPathRollsBackAndRethrows(): void
    {
        global $wpdb;

        $this->expectException(RuntimeException::class);
        $this->expectExceptionMessage('boom');

        try {
            $this->subject->invoke(static function (): void {
                throw new RuntimeException('boom');
            });
        } finally {
            $this->assertSame(array('START TRANSACTION', 'ROLLBACK'), $wpdb->queries);
            $this->assertNotContains('COMMIT', $wpdb->queries);
        }
    }

    public function testCommitFailureRollsBackAndReturnsAcxDbError(): void
    {
        global $wpdb;
        $wpdb->queryResults['COMMIT'] = false;

        $result = $this->subject->invoke(static fn () => 'committed-payload');

        $this->assertTrue(is_wp_error($result));
        $this->assertSame('acx_db_error', $result->get_error_code());
        $this->assertSame('Could not commit local transaction.', $result->get_error_message());
        $this->assertSame(array('START TRANSACTION', 'COMMIT', 'ROLLBACK'), $wpdb->queries);
    }

    public function testStartFailureReturnsAcxDbErrorWithoutRunningCallable(): void
    {
        global $wpdb;
        $wpdb->queryResults['START TRANSACTION'] = false;
        $callable_ran = false;

        $result = $this->subject->invoke(static function () use (&$callable_ran): string {
            $callable_ran = true;
            return 'should-not-run';
        });

        $this->assertFalse($callable_ran);
        $this->assertTrue(is_wp_error($result));
        $this->assertSame('acx_db_error', $result->get_error_code());
        $this->assertSame('Could not start local transaction.', $result->get_error_message());
        $this->assertSame(array('START TRANSACTION'), $wpdb->queries);
    }
}
