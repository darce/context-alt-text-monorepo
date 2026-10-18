<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Api\Services\DescriptionBudgetService;
use AltContext\Cli\DescriptionUsageCommand;
use AltContext\Tests\TestCase;

/**
 * @covers \AltContext\Cli\DescriptionUsageCommand
 */
class DescriptionUsageCommandTest extends TestCase
{
    protected function setUp(): void
    {
        parent::setUp();
        \WP_CLI::reset_cli_messages();
    }

    public function testCommandReportsUsageSummaryAndRecentErrors(): void
    {
        $budget = new DescriptionBudgetService();
        $budget->record_success(101, 'openai', 'gpt-4.1-mini', 1200, false, 'updated', 0.04, 'USD');
        $budget->record_error(102, 'openai', 'gpt-4.1-mini', 'rate_limited', 'Rate limited', true, 'provider');

        $command = new DescriptionUsageCommand();
        $command->__invoke([], []);

        $logs = implode("\n", \WP_CLI::$messages['log']);
        $this->assertStringContainsString('attempts=2', $logs);
        $this->assertStringContainsString('successes=1', $logs);
        $this->assertStringContainsString('failures=1', $logs);
        $this->assertStringContainsString('rate_limited', $logs);
        $this->assertStringContainsString('media_id=102', $logs);
        $this->assertStringContainsString('Description usage reported', \WP_CLI::$messages['success'][0]);
    }
}
