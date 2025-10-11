<?php

declare(strict_types=1);

namespace ContextAltText\Tests\Roster\Support;

final class RosterTestFactory
{
    /**
     * @param array<string,mixed> $overrides
     * @return array<string,mixed>
     */
    public static function entry(array $overrides = []): array
    {
        return array_replace(
            [
                'remoteId' => 'remote-id',
                'label' => 'Example Label',
                'type' => 'person',
                'metadata' => [],
                'referenceImages' => [],
                'updatedAt' => '2024-01-01T00:00:00Z',
            ],
            $overrides,
        );
    }
}
