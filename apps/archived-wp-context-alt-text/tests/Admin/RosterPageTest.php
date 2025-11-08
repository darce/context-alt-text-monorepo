<?php

declare(strict_types=1);

use ContextAltText\Admin\RosterPage;
use ContextAltText\Roster\RosterSyncScheduler;
use ContextAltText\Security\Security;
use ContextAltText\Services\Scan\MissingAltTextScanner;
use ContextAltText\Tests\Roster\Support\StubRosterService;
use PHPUnit\Framework\TestCase;

require_once __DIR__ . '/../bootstrap.php';
require_once __DIR__ . '/../Roster/Support/StubRosterService.php';

final class RosterPageTest extends TestCase
{
    protected function setUp(): void
    {
        parent::setUp();
        $GLOBALS['__cat_options'] = [];
        $GLOBALS['__cat_filters'] = [];
        $GLOBALS['__cat_actions'] = [];
        $GLOBALS['__cat_json_response'] = null;
        $GLOBALS['__cat_current_user_capabilities'] = [];
        $_REQUEST = [];
    }

    public function test_handle_ajax_actions_triggers_manual_sync(): void
    {
        update_option('cat_roster_sync_state', ['updated' => 1]);

        $_REQUEST = [
            '_wpnonce' => 'nonce-context-alt-text-roster',
            'command' => 'sync',
        ];

        $service = new StubRosterService();
        $service->shouldReportChanges = true;
        $scheduler = new RosterSyncScheduler($service, 600);

        $page = new RosterPage($service, new Security(), new MissingAltTextScanner(), $scheduler);
        $page->handle_ajax_actions();

        self::assertIsArray($GLOBALS['__cat_json_response']);
        self::assertTrue($GLOBALS['__cat_json_response']['success']);
        self::assertTrue($GLOBALS['__cat_json_response']['data']['changesApplied']);
        self::assertSame(['updated' => 1], $GLOBALS['__cat_json_response']['data']['state']);
    }

    public function test_handle_ajax_actions_rejects_unknown_command(): void
    {
        $_REQUEST = [
            '_wpnonce' => 'nonce-context-alt-text-roster',
            'command' => 'unknown',
        ];

        $service = new StubRosterService();
        $scheduler = new RosterSyncScheduler($service, 600);

        $page = new RosterPage($service, new Security(), new MissingAltTextScanner(), $scheduler);
        $page->handle_ajax_actions();

        self::assertIsArray($GLOBALS['__cat_json_response']);
        self::assertFalse($GLOBALS['__cat_json_response']['success']);
        self::assertSame(400, $GLOBALS['__cat_json_response']['status']);
    }

    public function test_handle_ajax_actions_requires_nonce(): void
    {
        $_REQUEST = [];

        $service = new StubRosterService();
        $scheduler = new RosterSyncScheduler($service, 600);

        $page = new RosterPage($service, new Security(), new MissingAltTextScanner(), $scheduler);
        $page->handle_ajax_actions();

        self::assertFalse($GLOBALS['__cat_json_response']['success']);
        self::assertSame(400, $GLOBALS['__cat_json_response']['status']);
    }

    public function test_handle_ajax_actions_requires_capabilities(): void
    {
        $GLOBALS['__cat_current_user_capabilities']['manage_options'] = false;

        $_REQUEST = [
            '_wpnonce' => 'nonce-context-alt-text-roster',
            'command' => 'sync',
        ];

        $service = new StubRosterService();
        $scheduler = new RosterSyncScheduler($service, 600);

        $page = new RosterPage($service, new Security(), new MissingAltTextScanner(), $scheduler);
        $page->handle_ajax_actions();

        self::assertFalse($GLOBALS['__cat_json_response']['success']);
        self::assertSame(403, $GLOBALS['__cat_json_response']['status']);
    }
}
