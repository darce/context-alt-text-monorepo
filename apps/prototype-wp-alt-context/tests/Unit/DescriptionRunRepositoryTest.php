<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Sovereign\Repositories\DescriptionRunRepository;
use AltContext\Support\LifecycleManager;
use AltContext\Tests\TestCase;

/**
 * @covers \AltContext\Sovereign\Repositories\DescriptionRunRepository
 * @covers \AltContext\Support\LifecycleManager
 */
class DescriptionRunRepositoryTest extends TestCase
{
    public function testActivationCreatesDescriptionRunLedgerTables(): void
    {
        (new LifecycleManager())->activate();

        $schema = implode("\n", $GLOBALS['__ac_dbdelta_queries']);

        $this->assertStringContainsString('CREATE TABLE wp_acx_description_runs', $schema);
        $this->assertStringContainsString('CREATE TABLE wp_acx_description_run_items', $schema);
        $this->assertStringContainsString('KEY idx_run_status (run_id, status)', $schema);
    }

    public function testCreateRunPersistsPendingItemsAndStatusSummary(): void
    {
        $repository = new DescriptionRunRepository();

        $repository->create_run('run-1', [101, 102], 2, 1);
        $status = $repository->get_run_status('run-1');

        $this->assertSame('run-1', $status['run_id']);
        $this->assertSame(2, $status['limit']);
        $this->assertSame(1, $status['batch_size']);
        $this->assertSame(2, $status['total_items']);
        $this->assertSame(2, $status['counts']['pending']);
        $this->assertSame([101, 102], array_column($status['items'], 'media_id'));
    }

    public function testUpdateItemStatusAndRetryableListing(): void
    {
        $repository = new DescriptionRunRepository();

        $repository->create_run('run-2', [201, 202, 203], 3, 2);
        $repository->update_item_status('run-2', 201, 'succeeded');
        $repository->update_item_status('run-2', 202, 'failed', 'backend_502', 'Backend unavailable.');
        $repository->update_item_status('run-2', 203, 'retryable', 'timeout', 'Timed out.');

        $status = $repository->get_run_status('run-2');
        $retryable = $repository->list_retryable_items('run-2');

        $this->assertSame(1, $status['counts']['succeeded']);
        $this->assertSame(1, $status['counts']['failed']);
        $this->assertSame(1, $status['counts']['retryable']);
        $this->assertSame([202, 203], array_column($retryable, 'media_id'));
        $this->assertSame('backend_502', $retryable[0]['error_code']);
    }
}
