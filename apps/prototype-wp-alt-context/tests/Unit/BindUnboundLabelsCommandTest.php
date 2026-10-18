<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Api\Services\PersonLabelBackfillService;
use AltContext\Cli\BindUnboundLabelsCommand;
use AltContext\Tests\TestCase;
use WP_CLI;

/**
 * @covers \AltContext\Cli\BindUnboundLabelsCommand
 */
class BindUnboundLabelsCommandTest extends TestCase
{
    protected function setUp(): void
    {
        parent::setUp();
        WP_CLI::reset_cli_messages();
    }

    public function testCommandClampsBatchSizeAndReportsBoundCreated(): void
    {
        $service = new class() extends PersonLabelBackfillService {
            public int $seenBatch = 0;
            public function backfill_tenant(string $tenant_id, int $batch_size = self::BATCH_SIZE, bool $dry_run = false): array
            {
                $this->seenBatch = $batch_size;
                return [
                    'bound' => 2,
                    'created' => 1,
                    'persons' => 2,
                    'skipped' => 0,
                    'examined' => 2,
                    'collisions' => 0,
                    'stalls' => 0,
                    'stalled' => false,
                    'empty' => false,
                ];
            }
        };

        $command = new BindUnboundLabelsCommand($service);
        $command([], ['batch-size' => 999]);

        $this->assertSame(PersonLabelBackfillService::BATCH_SIZE, $service->seenBatch);
        $this->assertStringContainsString('Bound 2 cluster(s) to 2 person(s), 1 created', WP_CLI::get_stdout());
    }

    public function testCommandDryRunAndEmptyTenant(): void
    {
        $service = new class() extends PersonLabelBackfillService {
            public bool $dry = false;
            public function backfill_tenant(string $tenant_id, int $batch_size = self::BATCH_SIZE, bool $dry_run = false): array
            {
                $this->dry = $dry_run;
                return [
                    'bound' => 0,
                    'created' => 0,
                    'persons' => 0,
                    'skipped' => 0,
                    'examined' => 0,
                    'collisions' => 0,
                    'stalls' => 0,
                    'stalled' => false,
                    'empty' => true,
                ];
            }
        };

        $command = new BindUnboundLabelsCommand($service);
        $command([], ['dry-run' => true]);

        $this->assertTrue($service->dry);
        $this->assertStringContainsString('Tenant has no unbound human-labelled clusters.', WP_CLI::get_stdout());
    }

    public function testCommandErrorsWhenStalled(): void
    {
        $service = new class() extends PersonLabelBackfillService {
            public function backfill_tenant(string $tenant_id, int $batch_size = self::BATCH_SIZE, bool $dry_run = false): array
            {
                return [
                    'bound' => 0,
                    'created' => 0,
                    'persons' => 0,
                    'skipped' => 3,
                    'examined' => 3,
                    'collisions' => 0,
                    'stalls' => 3,
                    'stalled' => true,
                    'empty' => false,
                ];
            }
        };

        $command = new BindUnboundLabelsCommand($service);
        $this->expectException(\RuntimeException::class);
        $command([], []);
    }
}
