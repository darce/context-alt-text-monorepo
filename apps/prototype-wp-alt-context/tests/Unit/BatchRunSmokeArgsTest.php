<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Tests\TestCase;
use RuntimeException;

require_once ACX_PLUGIN_DIR . 'scripts/localwp/batch-run-smoke-args.php';

class BatchRunSmokeArgsTest extends TestCase
{
    public function testParseBatchRunSmokeArgsReturnsDefaultsWhenNoArgsProvided(): void
    {
        $parsed = acx_parse_batch_run_smoke_args([]);

        self::assertSame(
            [
                'limit' => 100,
                'batch_size' => 5,
                'timeout_seconds' => 240,
                'poll_interval_ms' => 1000,
            ],
            $parsed
        );
    }

    public function testParseBatchRunSmokeArgsRejectsSeparator(): void
    {
        $this->expectException(RuntimeException::class);
        $this->expectExceptionMessage('Smoke arguments must not include the WP-CLI separator `--`.');

        acx_parse_batch_run_smoke_args(['--', '5', '240', '1000']);
    }

    public function testParseBatchRunSmokeArgsRejectsMissingValues(): void
    {
        $this->expectException(RuntimeException::class);
        $this->expectExceptionMessage('Expected either 0 or 4 smoke arguments.');

        acx_parse_batch_run_smoke_args(['10', '5', '240']);
    }

    public function testParseBatchRunSmokeArgsRejectsNonIntegerValues(): void
    {
        $this->expectException(RuntimeException::class);
        $this->expectExceptionMessage('Smoke argument `limit` must be an integer.');

        acx_parse_batch_run_smoke_args(['ten', '5', '240', '1000']);
    }

    public function testParseBatchRunSmokeArgsRejectsOutOfRangeValues(): void
    {
        $this->expectException(RuntimeException::class);
        $this->expectExceptionMessage('Smoke argument `poll_interval_ms` must be at least 100.');

        acx_parse_batch_run_smoke_args(['10', '5', '240', '99']);
    }
}
