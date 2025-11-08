<?php

declare(strict_types=1);

namespace ContextAltText\Tests\Roster\Support;

use ContextAltText\Domain\Roster\RosterService;
use ContextAltText\Security\Security;
use ContextAltText\Tests\Roster\Support\FakeRosterClient;

final class StubRosterService extends RosterService
{
    public int $syncCount = 0;
    public bool $shouldReportChanges = false;

    public function __construct()
    {
        parent::__construct(new Security(), new FakeRosterClient());
    }

    public function syncFromRemote(): bool
    {
        $this->syncCount++;

        return $this->shouldReportChanges;
    }
}
