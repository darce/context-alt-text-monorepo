<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Api\AnalysisJobsController;
use AltContext\Api\Services\ProjectionSyncService;
use AltContext\Sovereign\Sync\SyncPullJobInterface;
use AltContext\Sovereign\Sync\SyncPullResult;
use AltContext\Tests\TestCase;

/**
 * @covers \AltContext\Api\Services\ProjectionSyncService
 */
class ProjectionSyncServiceTest extends TestCase
{
    public function testMaybeTriggerProjectionSyncRunsBypassWhenInlinePayloadMissing(): void
    {
        $syncSpy = new ProjectionSyncServiceSyncPullSpy();
        $service = new ProjectionSyncService(new AnalysisJobsController(), null, $syncSpy);

        $jobId = '55555555-5555-5555-5555-555555555555';
        $service->maybe_trigger_projection_sync([
            'id' => $jobId,
            'status' => 'completed',
            'type' => 'clustering',
            'snapshot_version' => 22,
            'source_job_id' => $jobId,
            'projection_acknowledged_at' => null,
        ]);

        $this->assertTrue($syncSpy->performedBypass);
        $this->assertSame(1, $syncSpy->performBypassCount);
    }
}

class ProjectionSyncServiceSyncPullSpy implements SyncPullJobInterface
{
    public bool $performedBypass = false;
    public int $performBypassCount = 0;

    public function perform(string $tenant_id): SyncPullResult
    {
        return SyncPullResult::ok();
    }

    public function perform_bypass_cooldown(string $tenant_id): SyncPullResult
    {
        $this->performedBypass = true;
        ++$this->performBypassCount;

        return SyncPullResult::ok();
    }

    public function perform_projection_payload(string $tenant_id, array $payload): SyncPullResult
    {
        return SyncPullResult::ok();
    }
}
