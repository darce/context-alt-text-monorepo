<?php

declare(strict_types=1);

use ContextAltText\Domain\Roster\RosterService;
use ContextAltText\Tests\Roster\Support\FakeRosterClient;
use ContextAltText\Security\Security;
use PHPUnit\Framework\TestCase;

require_once __DIR__ . '/../bootstrap.php';
require_once __DIR__ . '/Support/FakeRosterClient.php';

final class RosterServiceFiltersTest extends TestCase
{
    protected function setUp(): void
    {
        parent::setUp();
        $GLOBALS['__cat_options'] = [];
        $GLOBALS['__cat_filters'] = [];
    }

    protected function tearDown(): void
    {
        parent::tearDown();
        $GLOBALS['__cat_filters'] = [];
    }

    public function test_get_local_roster_uses_filter(): void
    {
        add_filter('context_alt_text_roster_local_results', static fn() => [['id' => 1]]);

        $service = new RosterService(new Security(), new FakeRosterClient());
        $results = $service->getLocalRoster();

        self::assertSame([['id' => 1]], $results);
    }

    public function test_attach_reference_image_uses_filter(): void
    {
        add_filter(
            'context_alt_text_roster_attach_reference',
            static fn($default, $entryId) => $entryId === 1,
            10,
            2
        );

        $service = new RosterService(new Security(), new FakeRosterClient());
        self::assertTrue($service->attachReferenceImage(1, ['image' => 'foo']));
        self::assertFalse($service->attachReferenceImage(2, ['image' => 'foo']));
    }

    public function test_search_uses_filter(): void
    {
        add_filter('context_alt_text_roster_search_results', static fn() => [['id' => 42]]);

        $service = new RosterService(new Security(), new FakeRosterClient());
        $results = $service->search('term');

        self::assertSame([['id' => 42]], $results);
    }
}
