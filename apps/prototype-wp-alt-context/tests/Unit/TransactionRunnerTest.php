<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Sovereign\Sync\TransactionRunner;
use AltContext\Tests\TestCase;
use RuntimeException;

class TransactionRunnerTest extends TestCase
{
    public function testRunTransactionalRollsBackWhenCallbackThrows(): void
    {
        global $wpdb;

        try {
            TransactionRunner::run_transactional(
                static function (): void {
                    throw new RuntimeException('purge failed');
                }
            );
            $this->fail('Expected RuntimeException was not thrown.');
        } catch (RuntimeException $exception) {
            $this->assertSame('purge failed', $exception->getMessage());
        }

        $this->assertContains('START TRANSACTION', $wpdb->queries);
        $this->assertContains('ROLLBACK', $wpdb->queries);
        $this->assertNotContains('COMMIT', $wpdb->queries);
    }
}
