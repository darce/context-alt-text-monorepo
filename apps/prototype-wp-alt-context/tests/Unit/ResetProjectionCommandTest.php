<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Cli\ResetProjectionCommand;
use AltContext\Tests\TestCase;
use RuntimeException;

/**
 * @covers \AltContext\Cli\ResetProjectionCommand
 */
class ResetProjectionCommandTest extends TestCase
{
    protected function setUp(): void
    {
        parent::setUp();
        \WP_CLI::reset_cli_messages();
    }

    public function testResetWithoutYesFlagEmitsError(): void
    {
        $command = new ResetProjectionCommand();

        $this->expectException(RuntimeException::class);
        $this->expectExceptionMessage('Add --yes to confirm');

        $command->__invoke([], []);
    }

    public function testResetTruncatesAllThreeProjectionTables(): void
    {
        global $wpdb;

        $command = new ResetProjectionCommand();
        $command->__invoke([], ['yes' => true]);

        $this->assertContains('TRUNCATE TABLE `wp_acx_clusters`', $wpdb->queries);
        $this->assertContains('TRUNCATE TABLE `wp_acx_identity_members`', $wpdb->queries);
        $this->assertContains('TRUNCATE TABLE `wp_acx_sync_state`', $wpdb->queries);

        $this->assertNotEmpty(\WP_CLI::$messages['success']);
        $this->assertStringContainsString('Projection tables reset', \WP_CLI::$messages['success'][0]);
    }

    public function testResetLogsTableCountsWhenRowsExist(): void
    {
        global $wpdb;

        // Set up mock: get_var returns row counts for each COUNT(*) query.
        $wpdb->mockVar = 7;

        $command = new ResetProjectionCommand();
        $command->__invoke([], ['yes' => true]);

        $logMessages = implode("\n", \WP_CLI::$messages['log']);
        $this->assertStringContainsString('7', $logMessages);
    }

    public function testResetSucceedsEvenWhenTablesAreEmpty(): void
    {
        global $wpdb;

        $wpdb->mockVar = 0;

        $command = new ResetProjectionCommand();
        $command->__invoke([], ['yes' => true]);

        $this->assertNotEmpty(\WP_CLI::$messages['success']);
    }
}
