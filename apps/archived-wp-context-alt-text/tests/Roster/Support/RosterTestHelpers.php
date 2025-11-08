<?php

declare(strict_types=1);

namespace ContextAltText\Tests\Roster\Support;

final class RosterTestHelpers
{
    /**
     * @param array<string,mixed> $overrides
     * @return array<string,mixed>
     */
    public static function buildEntry(array $overrides = []): array
    {
        $defaults = [
            'remoteId' => 'remote-' . uniqid('', true),
            'label' => 'Sample Entry',
            'type' => 'person',
            'metadata' => [],
            'referenceImages' => [],
            'updatedAt' => '2024-01-01T00:00:00Z',
        ];

        return array_merge($defaults, $overrides);
    }
}
