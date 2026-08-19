<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Api\Api;
use AltContext\Api\RecognitionDataSource;
use AltContext\Tests\Stubs\SpySyncPullJob;
use AltContext\Tests\Stubs\TargetedSpySyncPullJob;
use AltContext\Tests\TestCase;

/**
 * R2-03 / R2-10: Api::handle_bootstrap_sync targeted-dispatch branch.
 *
 * @covers \AltContext\Api\Api
 */
class ApiBootstrapSyncTest extends TestCase
{
    public function testHandleBootstrapSyncWithClusterIdsRunsTargetedSnapshot(): void
    {
        $pullJob = new TargetedSpySyncPullJob();
        $api = new Api(null, null, null, $pullJob);
        $api->init();

        do_action(RecognitionDataSource::BOOTSTRAP_SYNC_HOOK, 'tenant-1', ['cluster-a']);

        $this->assertSame(
            [
                [
                    'tenant_id' => 'tenant-1',
                    'cluster_ids' => ['cluster-a'],
                ],
            ],
            $pullJob->targetedCalls
        );
        $this->assertSame([], $pullJob->bypassCalls);
        $this->assertSame([], $pullJob->performCalls);
    }

    public function testHandleBootstrapSyncLogsWhenIdsSuppliedToNonTargetedJob(): void
    {
        $GLOBALS['__ac_error_log'] = [];
        $pullJob = new SpySyncPullJob();
        $api = new Api(null, null, null, $pullJob);
        $api->init();

        do_action(RecognitionDataSource::BOOTSTRAP_SYNC_HOOK, 'tenant-1', ['cluster-a']);

        $this->assertSame(['tenant-1'], $pullJob->bypassCalls);
        $log = implode("\n", $GLOBALS['__ac_error_log']);
        $this->assertStringContainsString('cluster ids', $log);
        $this->assertStringContainsString('not targeted-capable', $log);
    }
}
