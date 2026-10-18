<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Tests\TestCase;

require_once ACX_PLUGIN_DIR . 'scripts/localwp/batch-run-smoke-diagnostics.php';

class BatchRunSmokeDiagnosticsTest extends TestCase
{
    public function testFormatBatchRunTimeoutMessageReturnsBaseMessageForEmptyChildStatuses(): void
    {
        self::assertSame(
            'BatchRun did not reach a terminal state before timeout.',
            acx_format_batch_run_timeout_message([])
        );
    }

    public function testFormatBatchRunTimeoutMessageIncludesChildJobDetails(): void
    {
        $message = acx_format_batch_run_timeout_message(
            [
                [
                    'job_id' => 'job-1',
                    'status' => 'running',
                    'message' => 'Queueing 5/5 items',
                ],
                [
                    'job_id' => 'job-2',
                    'status' => 'unavailable',
                ],
            ]
        );

        self::assertSame(
            'BatchRun did not reach a terminal state before timeout. Child jobs: job-1=running (Queueing 5/5 items), job-2=unavailable.',
            $message
        );
    }

    public function testFormatBatchRunTimeoutMessageFallsBackToBaseMessageWhenEntriesAreInvalid(): void
    {
        self::assertSame(
            'BatchRun did not reach a terminal state before timeout.',
            acx_format_batch_run_timeout_message(['not-an-array'])
        );
    }
}
