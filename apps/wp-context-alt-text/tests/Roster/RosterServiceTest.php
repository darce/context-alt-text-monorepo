<?php

declare(strict_types=1);

use ContextAltText\Domain\Roster\RosterService;
use ContextAltText\Roster\RosterClientException;
use ContextAltText\Security\Security;
use ContextAltText\Tests\Roster\Support\FakeRosterClient;
use ContextAltText\Tests\Roster\Support\RosterTestFactory;
use PHPUnit\Framework\TestCase;

require_once __DIR__ . '/../bootstrap.php';
require_once __DIR__ . '/Support/FakeRosterClient.php';
require_once __DIR__ . '/Support/RosterTestFactory.php';

final class RosterServiceTest extends TestCase
{
    protected function setUp(): void
    {
        parent::setUp();

        $GLOBALS['__cat_options'] = [];
        $GLOBALS['__cat_filters'] = [];
        unset(
            $GLOBALS['__cat_options']['cat_roster_sync_state'],
            $GLOBALS['__cat_options']['cat_roster_entries'],
            $GLOBALS['__cat_options']['cat_roster_entries_archived']
        );
    }

    protected function tearDown(): void
    {
        parent::tearDown();
        $GLOBALS['__cat_filters'] = [];
    }

    public function test_create_and_sync_updates_metrics_and_local_entries(): void
    {
        $client = new FakeRosterClient();

        $service = new RosterService(new Security(), $client);

        $result = $service->createAndSync(
            ['label' => 'Example', 'type' => 'person'],
            ['referenceImages' => [['image_url' => 'https://example.test/a.jpg']]]
        );

        self::assertSame(['id' => 'remote-1'], $result);
        self::assertSame(1, count($client->created));
        self::assertSame(1, count($client->embeddings));

        $entries = get_option('cat_roster_entries');
        self::assertIsArray($entries);
        self::assertArrayHasKey('remote-1', $entries);
        self::assertSame('Example', $entries['remote-1']['label']);

        $state = get_option('cat_roster_sync_state');
        self::assertIsArray($state);
        self::assertSame(1, $state['created']);
        self::assertSame(0, $state['errors']);
        self::assertArrayHasKey('lastSyncAt', $state);
    }

    public function test_update_and_sync_records_error_metrics(): void
    {
        $client = new FakeRosterClient();
        $client->responses['update'] = ['throw' => new RosterClientException('backend down', 503)];

        $service = new RosterService(new Security(), $client);

        $result = $service->updateAndSync(
            'remote-1',
            ['label' => 'Update', 'type' => 'person'],
            ['referenceImages' => [['image_url' => 'https://example.test/b.jpg']]]
        );

        self::assertNull($result);
        $state = get_option('cat_roster_sync_state');
        self::assertIsArray($state);
        self::assertSame(1, $state['errors']);
        self::assertSame('backend down', $state['lastError']['message']);
    }

    public function test_update_and_sync_persists_entry(): void
    {
        update_option('cat_roster_entries', [
            'remote-1' => RosterTestFactory::entry([
                'remoteId' => 'remote-1',
                'label' => 'Original',
                'type' => 'person',
            ]),
        ]);

        $client = new FakeRosterClient();
        $client->responses['update'] = [
            'id' => 'remote-1',
            'label' => 'Updated Label',
            'type' => 'person',
            'updated_at' => '2024-02-01T00:00:00Z',
        ];

        $service = new RosterService(new Security(), $client);
        $service->updateAndSync('remote-1', ['label' => 'Updated Label', 'type' => 'person']);

        $entries = get_option('cat_roster_entries');
        self::assertSame('Updated Label', $entries['remote-1']['label']);
        self::assertSame('2024-02-01T00:00:00Z', $entries['remote-1']['updatedAt']);
    }

    public function test_create_and_sync_blocks_duplicate_label_and_type(): void
    {
        update_option('cat_roster_entries', [
            'remote-existing' => RosterTestFactory::entry([
                'remoteId' => 'remote-existing',
                'label' => 'Example',
                'type' => 'person',
            ]),
        ]);

        $client = new FakeRosterClient();
        $service = new RosterService(new Security(), $client);

        $result = $service->createAndSync(['label' => 'Example', 'type' => 'person']);

        self::assertNull($result);

        $state = get_option('cat_roster_sync_state');
        self::assertSame(1, $state['errors']);
        self::assertSame(
            'Another roster entry already uses that label and type. Update the existing entry or choose a unique combination.',
            $state['lastError']['message'] ?? null
        );
    }

    public function test_create_and_sync_surfaces_friendly_message_on_remote_conflict(): void
    {
        $client = new FakeRosterClient();
        $client->responses['create']['throw'] = new RosterClientException('Conflict', 409);

        $service = new RosterService(new Security(), $client);

        $result = $service->createAndSync(['label' => 'Example', 'type' => 'person']);

        self::assertNull($result);

        $state = get_option('cat_roster_sync_state');
        self::assertSame(1, $state['errors']);
        self::assertSame(409, $state['lastError']['code']);
        self::assertSame(
            'Another roster entry already uses that label and type. Update the existing entry or choose a unique combination.',
            $state['lastError']['message'] ?? null
        );
    }

    public function test_sync_from_remote_merges_entries_and_updates_metrics(): void
    {
        update_option('cat_roster_entries', [
            'remote-1' => RosterTestFactory::entry([
                'remoteId' => 'remote-1',
                'label' => 'Local Label',
                'type' => 'person',
            ]),
        ]);

        add_filter('context_alt_text_roster_remote_snapshot', static fn() => [
            [
                'id' => 'remote-1',
                'label' => 'Remote Label',
                'type' => 'person',
                'updated_at' => '2024-02-01T00:00:00Z',
            ],
            [
                'id' => 'remote-2',
                'label' => 'New Entry',
                'type' => 'organization',
                'updated_at' => '2024-03-05T00:00:00Z',
            ],
        ]);

        $service = new RosterService(new Security(), new FakeRosterClient());
        self::assertTrue($service->syncFromRemote());

        $entries = get_option('cat_roster_entries');
        self::assertSame('Remote Label', $entries['remote-1']['label']);
        self::assertArrayHasKey('remote-2', $entries);

        $state = get_option('cat_roster_sync_state');
        self::assertSame(1, $state['updated']);
        self::assertSame(1, $state['created']);
    }

    public function test_sync_from_remote_detects_conflicts_when_remote_older(): void
    {
        update_option('cat_roster_entries', [
            'remote-3' => RosterTestFactory::entry([
                'remoteId' => 'remote-3',
                'label' => 'Local Entry',
                'type' => 'person',
                'updatedAt' => '2024-03-10T00:00:00Z',
            ]),
        ]);

        add_filter('context_alt_text_roster_remote_snapshot', static fn() => [
            [
                'id' => 'remote-3',
                'label' => 'Remote Entry',
                'type' => 'person',
                'updated_at' => '2024-02-01T00:00:00Z',
            ],
        ]);

        $service = new RosterService(new Security(), new FakeRosterClient());
        self::assertTrue($service->syncFromRemote());

        $entries = get_option('cat_roster_entries');
        self::assertSame('Local Entry', $entries['remote-3']['label']);

        $state = get_option('cat_roster_sync_state');
        self::assertSame(1, $state['conflicts']);
    }

    public function test_sync_from_remote_removes_entries_missing_from_snapshot(): void
    {
        update_option('cat_roster_entries', [
            'remote-keep' => RosterTestFactory::entry([
                'remoteId' => 'remote-keep',
                'label' => 'Keep Me',
                'type' => 'person',
                'updatedAt' => '2024-04-01T00:00:00Z',
            ]),
            'remote-remove' => RosterTestFactory::entry([
                'remoteId' => 'remote-remove',
                'label' => 'Remove Me',
                'type' => 'organization',
                'updatedAt' => '2024-03-01T00:00:00Z',
            ]),
        ]);

        add_filter('context_alt_text_roster_remote_snapshot', static fn() => [
            [
                'id' => 'remote-keep',
                'label' => 'Keep Me',
                'type' => 'person',
                'updated_at' => '2024-04-01T00:00:00Z',
            ],
        ]);

        $service = new RosterService(new Security(), new FakeRosterClient());
        self::assertTrue($service->syncFromRemote());

        $entries = get_option('cat_roster_entries');
        self::assertIsArray($entries);
        self::assertArrayHasKey('remote-keep', $entries);
        self::assertArrayNotHasKey('remote-remove', $entries);

        $archived = get_option('cat_roster_entries_archived');
        self::assertIsArray($archived);
        self::assertArrayHasKey('remote-remove', $archived);
        self::assertSame('Remove Me', $archived['remote-remove']['label']);
        self::assertArrayHasKey('archivedAt', $archived['remote-remove']);

        $state = get_option('cat_roster_sync_state');
        self::assertIsArray($state);
        self::assertSame(1, $state['deleted']);
        self::assertSame(0, $state['created']);
        self::assertSame(0, $state['updated']);
        self::assertSame(0, $state['conflicts']);
    }

    public function test_sync_from_remote_noops_when_snapshot_missing(): void
    {
        update_option('cat_roster_entries', [
            'remote-1' => RosterTestFactory::entry([
                'remoteId' => 'remote-1',
                'label' => 'Existing Entry',
            ]),
        ]);

        $service = new RosterService(new Security(), new FakeRosterClient());

        self::assertFalse($service->syncFromRemote());

        $entries = get_option('cat_roster_entries');
        self::assertArrayHasKey('remote-1', $entries);

        $state = get_option('cat_roster_sync_state', []);
        self::assertIsArray($state);
        self::assertSame(0, $state['created'] ?? 0);
        self::assertSame(0, $state['updated'] ?? 0);
        self::assertSame(0, $state['deleted'] ?? 0);
    }
}
