<?php

declare(strict_types=1);

namespace ContextAltText\Domain\Roster;

use ContextAltText\Roster\RosterClientException;
use ContextAltText\Roster\RosterRemote;
use ContextAltText\Security\Security;
use DateTimeImmutable;
use DateTimeInterface;
use Exception;
use function __;
use function apply_filters;
use function array_diff_key;
use function array_filter;
use function array_merge;
use function array_slice;
use function array_values;
use function current_time;
use function get_option;
use function is_array;
use function is_scalar;
use function sanitize_text_field;
use function mb_strtolower;
use function str_contains;
use function strtotime;

class RosterService
{
    use UsesRosterOptions;

    private Security $security;
    private RosterRemote $client;

    public function __construct(Security $security, RosterRemote $client)
    {
        $this->security = $security;
        $this->client = $client;
    }

    public function exists(string $label, string $type, $excludeId = null): bool
    {
        $entries = $this->loadLocalEntries();

        foreach ($entries as $remoteId => $entry) {
            if ($excludeId !== null && (string) $excludeId === (string) $remoteId) {
                continue;
            }

            if (
                isset($entry['label'], $entry['type']) &&
                $entry['label'] === $label &&
                $entry['type'] === $type
            ) {
                return true;
            }
        }

        return false;
    }

    public function getLocalRoster(array $filters = []): array
    {
        $entries = $this->loadLocalEntries();

        if (!empty($filters['type'])) {
            $type = (string) $filters['type'];
            $entries = array_filter(
                $entries,
                static fn($entry) => isset($entry['type']) && $entry['type'] === $type
            );
        }

        return apply_filters('context_alt_text_roster_local_results', array_values($entries), $filters);
    }

    public function syncFromRemote(): bool
    {
        $snapshot = apply_filters('context_alt_text_roster_remote_snapshot', null);

        if (!is_array($snapshot)) {
            return false;
        }

        $entries = $this->loadLocalEntries();
        $archived = $this->loadArchivedEntries();
        $created = 0;
        $updated = 0;
        $conflicts = 0;
        $deleted = 0;

        $seenRemoteIds = [];

        foreach ($snapshot as $record) {
            if (!is_array($record)) {
                continue;
            }

            $normalized = $this->normalizeRemoteEntry($record);
            $remoteId = $normalized['remoteId'] ?? null;

            if (!$remoteId) {
                continue;
            }

            $seenRemoteIds[$remoteId] = true;
            $existing = $entries[$remoteId] ?? null;

            if ($existing === null) {
                $entries[$remoteId] = $normalized;
                $created++;
                continue;
            }

            if ($this->isRemoteNewer($normalized, $existing)) {
                $entries[$remoteId] = array_merge($existing, $normalized);
                $updated++;
                continue;
            }

            if ($this->isConflict($normalized, $existing)) {
                $conflicts++;
            }
        }

        $missingRemoteIds = array_diff_key($entries, $seenRemoteIds);
        if ($missingRemoteIds !== []) {
            foreach ($missingRemoteIds as $remoteId => $entry) {
                unset($entries[$remoteId]);
                $archived[$remoteId] = array_merge($entry, [
                    'archivedAt' => $this->currentTimestamp(),
                ]);
                $deleted++;
            }
        }

        if ($created === 0 && $updated === 0 && $conflicts === 0 && $deleted === 0) {
            return false;
        }

        $this->saveLocalEntries($entries);
        $this->saveArchivedEntries($archived);

        if ($created > 0) {
            $this->recordSyncMetrics('created', $created);
        }

        if ($updated > 0) {
            $this->recordSyncMetrics('updated', $updated);
        }

        if ($conflicts > 0) {
            $this->recordSyncMetrics('conflicts', $conflicts);
        }

        if ($deleted > 0) {
            $this->recordSyncMetrics('deleted', $deleted);
        }

        return true;
    }

    public function createAndSync(array $data, array $options = []): ?array
    {
        $errors = $this->validate($data);
        if (!empty($errors)) {
            return null;
        }

        $label = (string) ($data['label'] ?? '');
        $type = (string) ($data['type'] ?? '');

        if ($label !== '' && $type !== '' && $this->exists($label, $type)) {
            $exception = $this->createDuplicateLabelTypeException();
            $this->recordSyncMetrics('errors', 1, $exception);

            return null;
        }

        $payload = $this->buildRosterPayload($data, $options);

        try {
            $embeddings = $this->maybeGenerateEmbeddings($options);
            if ($embeddings !== []) {
                $payload['embeddings'] = $embeddings;
            }

            $response = $this->client->createEntry($payload);
            $this->persistEntry($response, $data, $options);
            $this->recordSyncMetrics('created', 1);

            return $response;
        } catch (RosterClientException $exception) {
            $this->recordSyncMetrics('errors', 1, $this->mapExceptionForMetrics($exception));

            return null;
        }
    }

    public function updateAndSync($id, array $data, array $options = []): ?array
    {
        $errors = $this->validate($data);
        if (!empty($errors)) {
            return null;
        }

        $remoteId = (string) $id;

        $payload = $this->buildRosterPayload($data, $options);

        $label = (string) ($payload['label'] ?? '');
        $type = (string) ($payload['type'] ?? '');

        if ($label !== '' && $type !== '' && $this->exists($label, $type, $remoteId)) {
            $exception = $this->createDuplicateLabelTypeException();
            $this->recordSyncMetrics('errors', 1, $exception);

            return null;
        }

        try {
            $embeddings = $this->maybeGenerateEmbeddings($options);
            if ($embeddings !== []) {
                $payload['embeddings'] = $embeddings;
            }

            $response = $this->client->updateEntry($remoteId, $payload);
            $this->persistEntry(array_merge($response, ['id' => $remoteId]), $data, $options);
            $this->recordSyncMetrics('updated', 1);

            return $response;
        } catch (RosterClientException $exception) {
            $this->recordSyncMetrics('errors', 1, $this->mapExceptionForMetrics($exception));

            return null;
        }
    }

    public function attachReferenceImage($entryId, $reference): bool
    {
        $remoteId = (string) $entryId;
        $entries = $this->loadLocalEntries();
        $result = false;

        if (isset($entries[$remoteId]) && is_array($reference)) {
            $entry = $entries[$remoteId];

            $images = $entry['referenceImages'] ?? [];
            if (!is_array($images)) {
                $images = [];
            }

            $images[] = $reference;
            $entry['referenceImages'] = array_values($images);
            $entry['updatedAt'] = $this->currentTimestamp();

            $entries[$remoteId] = $entry;
            $this->saveLocalEntries($entries);
            $this->recordSyncMetrics('updated', 1);
            $result = true;
        }

        return apply_filters('context_alt_text_roster_attach_reference', $result, $entryId, $reference);
    }

    public function search(string $query, int $limit = 20): array
    {
        $needle = trim($query);
        $entries = $this->loadLocalEntries();

        if ($needle !== '') {
            $lower = mb_strtolower($needle);
            $entries = array_filter(
                $entries,
                static function ($entry) use ($lower) {
                    $haystacks = [
                        mb_strtolower($entry['label'] ?? ''),
                        mb_strtolower($entry['type'] ?? ''),
                    ];

                    foreach ($haystacks as $value) {
                        if (str_contains($value, $lower)) {
                            return true;
                        }
                    }

                    return false;
                }
            );
        }

        $entries = array_slice(array_values($entries), 0, $limit);

        return apply_filters('context_alt_text_roster_search_results', $entries, $query, $limit);
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

    /**
     * @param array<string,mixed> $data
     * @param array<string,mixed> $options
     * @return array<string,mixed>
     */
    private function buildRosterPayload(array $data, array $options = []): array
    {
        $payload = [
            'label' => $data['label'] ?? '',
            'type' => $data['type'] ?? '',
            'metadata' => [],
        ];

        if (!empty($data['metadata']) && is_array($data['metadata'])) {
            $payload['metadata'] = $data['metadata'];
        }

        return apply_filters('context_alt_text_roster_payload', $payload, $data, $options);
    }

    /**
     * @param array<string,mixed> $response
     * @param array<string,mixed> $data
     * @param array<string,mixed> $options
     */
    private function persistEntry(array $response, array $data = [], array $options = []): void
    {
        $entry = $this->normalizeRemoteEntry($response, array_merge($data, $options));

        if (empty($entry['remoteId'])) {
            return;
        }

        $entries = $this->loadLocalEntries();
        $remoteId = $entry['remoteId'];

        $entries[$remoteId] = array_merge($entries[$remoteId] ?? [], $entry);

        $this->saveLocalEntries($entries);
    }

    /**
     * @param array<string,mixed> $default
     * @param array<string,mixed> $fallback
     * @return array<string,mixed>
     */
    private function normalizeRemoteEntry(array $default, array $fallback = []): array
    {
        $remoteId = $this->sanitizeNullable($default['id'] ?? $default['remote_id'] ?? $fallback['remoteId'] ?? null);

        $label = $this->sanitizeNullable($default['label'] ?? $fallback['label'] ?? null);
        $type = $this->sanitizeNullable($default['type'] ?? $fallback['type'] ?? null);
        $updatedAt = $this->sanitizeNullable($default['updated_at'] ?? $default['updatedAt'] ?? $fallback['updatedAt'] ?? null);

        $metadata = [];
        if (isset($default['metadata']) && is_array($default['metadata'])) {
            $metadata = $default['metadata'];
        } elseif (isset($fallback['metadata']) && is_array($fallback['metadata'])) {
            $metadata = $fallback['metadata'];
        }

        $referenceImages = [];
        if (isset($default['reference_images']) && is_array($default['reference_images'])) {
            $referenceImages = $default['reference_images'];
        } elseif (isset($fallback['referenceImages']) && is_array($fallback['referenceImages'])) {
            $referenceImages = $fallback['referenceImages'];
        }

        return [
            'remoteId' => $remoteId,
            'label' => $label,
            'type' => $type,
            'metadata' => $metadata,
            'referenceImages' => $referenceImages,
            'updatedAt' => $updatedAt ?: $this->currentTimestamp(),
        ];
    }

    /**
     * @param array<string,mixed> $options
     * @return array<string,mixed>
     */
    private function maybeGenerateEmbeddings(array $options): array
    {
        if (empty($options['referenceImages']) || !is_array($options['referenceImages'])) {
            return [];
        }

        try {
            return $this->client->generateEmbeddings([
                'images' => $options['referenceImages'],
            ]);
        } catch (RosterClientException $exception) {
            $this->recordSyncMetrics('errors', 1, $exception);

            return [];
        }
    }

    /**
     * @param array<string,mixed> $remote
     * @param array<string,mixed> $local
     */
    private function isRemoteNewer(array $remote, array $local): bool
    {
        if (empty($remote['updatedAt'])) {
            return false;
        }

        $remoteTime = strtotime((string) $remote['updatedAt']);
        $localTime = strtotime((string) ($local['updatedAt'] ?? ''));

        if ($remoteTime === false) {
            return false;
        }

        if ($localTime === false) {
            return true;
        }

        return $remoteTime > $localTime;
    }

    private function mapExceptionForMetrics(RosterClientException $exception): RosterClientException
    {
        if ($exception->getCode() === 409) {
            return $this->createDuplicateLabelTypeException();
        }

        return $exception;
    }

    private function createDuplicateLabelTypeException(): RosterClientException
    {
        return new RosterClientException(
            __('Another roster entry already uses that label and type. Update the existing entry or choose a unique combination.', 'context-alt-text'),
            409
        );
    }

    /**
     * @param array<string,mixed> $remote
     * @param array<string,mixed> $local
     */
    private function isConflict(array $remote, array $local): bool
    {
        return (
            isset($remote['label'], $local['label']) && $remote['label'] !== $local['label']
        ) || (
            isset($remote['type'], $local['type']) && $remote['type'] !== $local['type']
        );
    }

    private function sanitizeNullable($value): ?string
    {
        if (!is_scalar($value)) {
            return null;
        }

        $sanitized = sanitize_text_field((string) $value);

        return $sanitized !== '' ? $sanitized : null;
    }

    private function currentTimestamp(): string
    {
        try {
            $now = new DateTimeImmutable('@' . current_time('timestamp', true));

            return $now->format(DateTimeInterface::ATOM);
        } catch (Exception $exception) {
            return gmdate(DateTimeInterface::ATOM);
        }
    }
}
