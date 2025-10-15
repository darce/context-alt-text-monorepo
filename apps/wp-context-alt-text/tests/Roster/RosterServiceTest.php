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

        self::assertIsArray($result);
        self::assertTrue($result['success']);
        self::assertSame('remote-1', $result['entry']['unique_id'] ?? null);
        self::assertSame(1, count($client->created));
        self::assertSame(1, count($client->embeddings));
        self::assertSame(
            [
                'embedding' => [0.1, 0.2],
                'image_path' => 'https://example.test/a.jpg',
            ],
            $client->created[0]['embeddings'][0] ?? null
        );

        $entries = get_option('cat_roster_entries');
        self::assertIsArray($entries);
        self::assertArrayHasKey('remote-1', $entries);
        self::assertSame('Example', $entries['remote-1']['label']);
        self::assertSame('https://example.test/a.jpg', $entries['remote-1']['referenceImages'][0]['image_url'] ?? null);
        self::assertArrayHasKey('syncedAt', $entries['remote-1']['referenceImages'][0]);

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
            'message' => 'Reference embedding appended',
            'entry' => [
                'unique_id' => 'remote-1',
                'name' => 'Example',
                'display_name' => 'Updated Label',
                'metadata' => [],
                'reference_images' => [],
                'updated_timestamp' => '2024-02-01T00:00:00Z',
            ],
        ];

        $service = new RosterService(new Security(), $client);
        $service->updateAndSync('remote-1', ['label' => 'Updated Label', 'type' => 'person']);

        $entries = get_option('cat_roster_entries');
        self::assertSame('Updated Label', $entries['remote-1']['label']);
        self::assertSame('2024-02-01T00:00:00Z', $entries['remote-1']['updatedAt']);
    }

    public function test_create_and_sync_reuses_existing_entry_on_duplicate(): void
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

        self::assertIsArray($result);
        self::assertSame('remote-existing', $result['id']);
        self::assertSame([], $client->created);
        self::assertSame([], $client->updated);
        self::assertSame([], $client->embeddings);

        $state = get_option('cat_roster_sync_state') ?? [];
        self::assertIsArray($state);
        self::assertSame(0, $state['errors'] ?? 0);
        self::assertArrayNotHasKey('lastError', $state);
    }

    public function test_create_and_sync_append_reference_images_when_duplicate(): void
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

        $result = $service->createAndSync(
            ['label' => 'Example', 'type' => 'person'],
            [
                'referenceImages' => [
                    [
                        'image_url' => 'https://example.test/image.jpg',
                        'metadata' => ['source' => 'recognition'],
                    ],
                ],
            ]
        );

        self::assertIsArray($result);
        self::assertSame('remote-existing', $result['id']);
        self::assertSame([], $client->created);
        self::assertCount(1, $client->updated);
        self::assertCount(1, $client->embeddings);

        $state = get_option('cat_roster_sync_state') ?? [];
        self::assertIsArray($state);
        self::assertSame(1, $state['updated']);
        self::assertSame(0, $state['errors'] ?? 0);
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

    public function test_delete_and_archive_removes_entry(): void
    {
        update_option('cat_roster_entries', [
            'remote-1' => RosterTestFactory::entry([
                'remoteId' => 'remote-1',
                'label' => 'Delete Me',
            ]),
        ]);

        $client = new FakeRosterClient();
        $service = new RosterService(new Security(), $client);

        self::assertTrue($service->deleteAndArchive('remote-1'));

        $entries = get_option('cat_roster_entries');
        self::assertIsArray($entries);
        self::assertArrayNotHasKey('remote-1', $entries);

        $archived = get_option('cat_roster_entries_archived');
        self::assertIsArray($archived);
        self::assertArrayHasKey('remote-1', $archived);
        self::assertSame('Delete Me', $archived['remote-1']['label']);

        self::assertCount(1, $client->deleted);

        $state = get_option('cat_roster_sync_state');
        self::assertSame(1, $state['deleted']);
    }

    public function test_attach_reference_image_syncs_remote_reference(): void
    {
        update_option('cat_roster_entries', [
            'remote-1' => RosterTestFactory::entry([
                'remoteId' => 'remote-1',
                'referenceImages' => [],
            ]),
        ]);

        $client = new FakeRosterClient();
        $client->responses['embeddings'] = [
            'faces' => [
                ['embedding' => [0.42, 0.58]],
            ],
        ];

        $service = new RosterService(new Security(), $client);

        $reference = [
            'image_url' => 'https://example.test/new.jpg',
            'thumbnail_url' => 'https://example.test/thumb-new.jpg',
            'metadata' => ['source' => 'observation:42'],
        ];

        self::assertTrue($service->attachReferenceImage('remote-1', $reference));

        self::assertCount(1, $client->appended);
        self::assertSame('remote-1', $client->appended[0]['remoteId']);
        self::assertSame([0.42, 0.58], $client->appended[0]['payload']['embedding']);
        self::assertSame('https://example.test/new.jpg', $client->appended[0]['payload']['image_path'] ?? null);

        $entries = get_option('cat_roster_entries');
        self::assertSame('https://example.test/new.jpg', $entries['remote-1']['referenceImages'][0]['image_url'] ?? null);
        self::assertSame('https://example.test/thumb-new.jpg', $entries['remote-1']['referenceImages'][0]['thumbnail_url'] ?? null);
        self::assertSame('observation:42', $entries['remote-1']['referenceImages'][0]['metadata']['source'] ?? null);

        $state = get_option('cat_roster_sync_state');
        self::assertSame(1, $state['updated']);
        self::assertSame(0, $state['errors']);
    }

    public function test_delete_and_archive_handles_remote_failure(): void
    {
        update_option('cat_roster_entries', [
            'remote-2' => RosterTestFactory::entry([
                'remoteId' => 'remote-2',
            ]),
        ]);

        $client = new FakeRosterClient();
        $client->responses['delete']['result'] = false;

        $service = new RosterService(new Security(), $client);

        self::assertFalse($service->deleteAndArchive('remote-2'));

        $entries = get_option('cat_roster_entries');
        self::assertArrayHasKey('remote-2', $entries);

        $state = get_option('cat_roster_sync_state');
        self::assertSame(1, $state['errors']);
        self::assertSame(0, $state['deleted']);
    }

    public function test_get_entry_by_id_returns_entry(): void
    {
        update_option('cat_roster_entries', [
            'remote-3' => RosterTestFactory::entry([
                'remoteId' => 'remote-3',
                'label' => 'Lookup',
            ]),
        ]);

        $service = new RosterService(new Security(), new FakeRosterClient());

        $entry = $service->getEntryById('remote-3');
        self::assertNotNull($entry);
        self::assertSame('Lookup', $entry['label']);

        self::assertNull($service->getEntryById('missing'));
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
