<?php

declare(strict_types=1);

namespace ContextAltText\Domain\Roster;

use ContextAltText\Roster\RosterClientException;
use function get_option;
use function is_array;
use function update_option;

/**
 * Shared helpers for working with roster-related WordPress options.
 */
trait UsesRosterOptions
{
    private const OPTION_ENTRIES = 'cat_roster_entries';
    private const OPTION_ARCHIVED = 'cat_roster_entries_archived';
    private const OPTION_SYNC_STATE = 'cat_roster_sync_state';

    /**
     * @return array<string,mixed>
     */
    protected function loadLocalEntries(): array
    {
        return $this->loadOption(self::OPTION_ENTRIES);
    }

    /**
     * @param array<string,mixed> $entries
     */
    protected function saveLocalEntries(array $entries): void
    {
        $this->saveOption(self::OPTION_ENTRIES, $entries);
    }

    /**
     * @return array<string,mixed>
     */
    protected function loadArchivedEntries(): array
    {
        return $this->loadOption(self::OPTION_ARCHIVED);
    }

    /**
     * @param array<string,mixed> $entries
     */
    protected function saveArchivedEntries(array $entries): void
    {
        $this->saveOption(self::OPTION_ARCHIVED, $entries);
    }

    protected function recordSyncMetrics(string $metric, int $count = 1, ?RosterClientException $exception = null): void
    {
        $state = $this->loadOption(self::OPTION_SYNC_STATE);

        if (!isset($state['lastSyncAt'])) {
            $state = array_merge([
                'lastSyncAt' => null,
                'created' => 0,
                'updated' => 0,
                'deleted' => 0,
                'errors' => 0,
                'conflicts' => 0,
            ], $state);
        }

        $state[$metric] = ($state[$metric] ?? 0) + $count;
        $state['lastSyncAt'] = $this->currentTimestamp();

        if ($exception !== null) {
            $state['lastError'] = [
                'message' => $exception->getMessage(),
                'code' => $exception->getCode(),
            ];
        }

        $this->saveOption(self::OPTION_SYNC_STATE, $state);
    }

    /**
     * @return array<string,mixed>
     */
    private function loadOption(string $option): array
    {
        $value = get_option($option);

        if (!is_array($value)) {
            return [];
        }

        return $value;
    }

    /**
     * @param array<string,mixed> $value
     */
    private function saveOption(string $option, array $value): void
    {
        update_option($option, $value);
    }

    abstract protected function currentTimestamp(): string;
}
