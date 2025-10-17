<?php

declare(strict_types=1);

use ContextAltText\Domain\Roster\RosterService;
use ContextAltText\Roster\RosterCli;
use ContextAltText\Roster\RosterTaxonomy;
use ContextAltText\Tests\Roster\Support\FakeRosterClient;
use ContextAltText\Security\Security;
use PHPUnit\Framework\TestCase;

require_once __DIR__ . '/../bootstrap.php';
require_once __DIR__ . '/Support/FakeRosterClient.php';

final class RosterCliTest extends TestCase
{
    protected function setUp(): void
    {
        parent::setUp();

        WP_CLI::reset_cli_messages();
        $GLOBALS['__cat_options'] = [];
    }

    public function test_status_outputs_metrics(): void
    {
        update_option('cat_roster_sync_state', [
            'lastSyncAt' => '2024-01-01T00:00:00Z',
            'created' => 2,
            'updated' => 1,
            'deleted' => 0,
            'errors' => 0,
            'conflicts' => 0,
        ]);

        $cli = new RosterCli(
            new RosterService(new Security(), new FakeRosterClient()),
            new RosterTaxonomy()
        );
        $cli->status([], []);

        self::assertNotEmpty(WP_CLI::$messages['log']);
        self::assertStringContainsString('Roster Sync Metrics', WP_CLI::$messages['log'][0]);
        self::assertSame('Roster status fetched.', WP_CLI::$messages['success'][0]);
    }

    public function test_sync_outputs_warning_when_service_reports_no_changes(): void
    {
        $service = new class(new Security(), new FakeRosterClient()) extends RosterService {
            public function syncFromRemote(): bool
            {
                return false;
            }
        };

        $cli = new RosterCli($service, new RosterTaxonomy());
        $cli->sync([], []);

        self::assertSame('Roster sync did not report any changes.', WP_CLI::$messages['warning'][0]);
    }

    public function test_sync_outputs_success_when_service_reports_changes(): void
    {
        $service = new class(new Security(), new FakeRosterClient()) extends RosterService {
            public function syncFromRemote(): bool
            {
                return true;
            }
        };

        $cli = new RosterCli($service, new RosterTaxonomy());
        $cli->sync([], []);

        self::assertSame('Roster sync completed.', WP_CLI::$messages['success'][0]);
    }
}
