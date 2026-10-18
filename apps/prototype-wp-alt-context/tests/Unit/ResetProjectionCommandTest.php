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

    public function testResetEmitsOnlyTheThreeProjectionTruncatesAndNoOtherDestructiveQueries(): void
    {
        global $wpdb;

        $command = new ResetProjectionCommand();
        $command->__invoke([], ['yes' => true]);

        $truncates = array_values(array_filter(
            $wpdb->queries,
            static fn (string $query): bool => str_starts_with($query, 'TRUNCATE TABLE'),
        ));

        // Reset surface is contractually limited to the three projection tables.
        $this->assertSame(
            [
                'TRUNCATE TABLE `wp_acx_clusters`',
                'TRUNCATE TABLE `wp_acx_identity_members`',
                'TRUNCATE TABLE `wp_acx_sync_state`',
            ],
            $truncates,
            'Reset must truncate exactly the three documented projection tables — '
            . 'expansion requires a planning-reviewed projection/read contract change.'
        );

        // No DELETE / DROP destructive verbs are allowed on the reset path.
        foreach ($wpdb->queries as $query) {
            $this->assertDoesNotMatchRegularExpression(
                '/^(DELETE|DROP)\b/i',
                $query,
                sprintf('Unexpected destructive query on reset path: %s', $query)
            );
        }
    }
}
