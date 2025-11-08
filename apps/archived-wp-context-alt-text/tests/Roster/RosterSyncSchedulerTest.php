<?php

declare(strict_types=1);

use ContextAltText\Roster\RosterSyncScheduler;
use ContextAltText\Tests\Roster\Support\StubRosterService;
use PHPUnit\Framework\TestCase;

require_once __DIR__ . '/../bootstrap.php';
require_once __DIR__ . '/Support/RosterTestFactory.php';
require_once __DIR__ . '/Support/StubRosterService.php';

final class RosterSyncSchedulerTest extends TestCase
{
    protected function setUp(): void
    {
        parent::setUp();

        $GLOBALS['__cat_options'] = [];
        $GLOBALS['__cat_filters'] = [];
        $GLOBALS['__cat_actions'] = [];
        $GLOBALS['__cat_scheduled'] = [];
    }

    public function test_activate_schedules_event(): void
    {
        $service = new StubRosterService();
        $scheduler = new RosterSyncScheduler($service, 600);

        $scheduler->activate();

        self::assertNotFalse(wp_next_scheduled(RosterSyncScheduler::HOOK));
    }

    public function test_handle_scheduled_sync_invokes_service_and_reschedules(): void
    {
        $service = new StubRosterService();
        $scheduler = new RosterSyncScheduler($service, 600);

        $scheduler->handleScheduledSync();

        self::assertSame(1, $service->syncCount);
        self::assertNotFalse(wp_next_scheduled(RosterSyncScheduler::HOOK));
    }

    public function test_run_manual_sync_returns_state(): void
    {
        $service = new StubRosterService();
        $service->shouldReportChanges = true;

        update_option('cat_roster_sync_state', ['created' => 2, 'lastSyncAt' => 'now']);

        $scheduler = new RosterSyncScheduler($service, 600);
        $result = $scheduler->runManualSync();

        self::assertTrue($result['changesApplied']);
        self::assertSame(['created' => 2, 'lastSyncAt' => 'now'], $result['state']);
    }
}
