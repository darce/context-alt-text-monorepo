<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Api\Services\DescriptionBulkRunService;
use AltContext\Sovereign\Repositories\DescriptionRunRepository;
use AltContext\Tests\TestCase;
use RuntimeException;

/**
 * @covers \AltContext\Api\Services\DescriptionBulkRunService
 */
class DescriptionBulkRunServiceTest extends TestCase
{
    public function testRunProcessesBoundedCandidatesAndRecordsFailures(): void
    {
        $repository = new DescriptionRunRepository();
        $processed = [];
        $service = new DescriptionBulkRunService(
            $repository,
            static function (int $mediaId) use (&$processed): array {
                $processed[] = $mediaId;
                if ($mediaId === 302) {
                    return ['status' => 'retryable', 'error_code' => 'backend_502', 'error_message' => 'Backend unavailable.'];
                }

                return ['status' => 'succeeded'];
            }
        );

        $status = $service->run([301, 302, 303], 2, 1, 'bulk-1');

        $this->assertSame([301, 302], $processed);
        $this->assertSame('bulk-1', $status['run_id']);
        $this->assertSame(2, $status['total_items']);
        $this->assertSame(1, $status['counts']['succeeded']);
        $this->assertSame(1, $status['counts']['retryable']);
        $this->assertSame([302], array_column($repository->list_retryable_items('bulk-1'), 'media_id'));
    }

    public function testRunRejectsUnboundedInputs(): void
    {
        $service = new DescriptionBulkRunService(new DescriptionRunRepository());

        $this->expectException(RuntimeException::class);
        $this->expectExceptionMessage('Bulk description runs require limit and batch_size of at least 1.');

        $service->run([401], 0, 1, 'bulk-2');
    }

    public function testRetryProcessesOnlyFailedAndRetryableItems(): void
    {
        $repository = new DescriptionRunRepository();
        $repository->create_run('bulk-3', [501, 502, 503], 3, 2);
        $repository->update_item_status('bulk-3', 501, 'succeeded');
        $repository->update_item_status('bulk-3', 502, 'failed', 'timeout', 'Timed out.');
        $repository->update_item_status('bulk-3', 503, 'retryable', 'backend_502', 'Backend unavailable.');

        $processed = [];
        $service = new DescriptionBulkRunService(
            $repository,
            static function (int $mediaId) use (&$processed): array {
                $processed[] = $mediaId;
                return ['status' => 'succeeded'];
            }
        );

        $status = $service->retry('bulk-3');

        $this->assertSame([502, 503], $processed);
        $this->assertSame(3, $status['counts']['succeeded']);
        $this->assertSame([], $repository->list_retryable_items('bulk-3'));
    }
}
