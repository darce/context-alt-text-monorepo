<?php

declare(strict_types=1);

namespace ContextAltText\Domain\Roster;

use ContextAltText\Security\Security;

class RosterService
{
    private Security $security;

    public function __construct(Security $security)
    {
        $this->security = $security;
    }

    public function exists(string $label, string $type, $excludeId = null): bool
    {
        // Persistence layer wiring will land with the roster migrations.
        return false;
    }

    public function getLocalRoster(array $filters = []): array
    {
        return [];
    }

    public function syncFromRemote(): bool
    {
        return false;
    }

    public function createAndSync(array $data, array $options = []): ?array
    {
        return null;
    }

    public function updateAndSync($id, array $data, array $options = []): ?array
    {
        return null;
    }

    public function attachReferenceImage($entryId, $reference): bool
    {
        return false;
    }

    public function search(string $query, int $limit = 20): array
    {
        return [];
    }

    public function validate(array $data): array
    {
        $errors = [];

        if (empty($data['label'])) {
            $errors['label'] = __('Label is required.', 'context-alt-text');
        }

        if (empty($data['type'])) {
            $errors['type'] = __('Type is required.', 'context-alt-text');
        }

        return $errors;
    }
}
