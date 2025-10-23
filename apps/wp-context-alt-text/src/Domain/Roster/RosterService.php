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
use function array_map;
use function array_merge;
use function array_slice;
use function array_values;
use function call_user_func;
use function current_time;
use function esc_url_raw;
use function function_exists;
use function base64_encode;
use function file_exists;
use function file_get_contents;
use function get_option;
use function get_post;
use function get_edit_post_link;
use function is_array;
use function is_numeric;
use function is_scalar;
use function is_string;
use function mb_strtolower;
use function preg_replace;
use function sanitize_text_field;
use function str_contains;
use function strtotime;
use function trim;
use function wp_get_attachment_image_url;
use function wp_get_attachment_url;

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

        if ($label !== '' && $type !== '') {
            $existing = $this->findLocalEntryByLabelAndType($label, $type);

            if ($existing !== null) {
                $duplicateResult = $this->handleDuplicateCreateRequest($existing, $data, $options);

                if ($duplicateResult !== null) {
                    return $duplicateResult;
                }

                return null;
            }
        }

        $payload = $this->buildRosterPayload($data, $options);

        try {
            $embeddings = $this->maybeGenerateEmbeddings($options);
            if ($embeddings !== []) {
                $payload['embeddings'] = $this->mapEmbeddingsForPayload($embeddings);
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
                $payload['embeddings'] = $this->mapEmbeddingsForPayload($embeddings);
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

    public function deleteAndArchive($id): bool
    {
        $remoteId = (string) $id;
        $entries = $this->loadLocalEntries();

        if (!isset($entries[$remoteId])) {
            return false;
        }

        try {
            $deleted = $this->client->deleteEntry($remoteId);
        } catch (RosterClientException $exception) {
            $this->recordSyncMetrics('errors', 1, $exception);

            return false;
        }

        if (!$deleted) {
            $this->recordSyncMetrics(
                'errors',
                1,
                new RosterClientException(
                    __('The recognition service did not confirm deletion of the roster entry.', 'context-alt-text'),
                    500
                )
            );

            return false;
        }

        $archived = $this->loadArchivedEntries();
        $archived[$remoteId] = array_merge(
            $entries[$remoteId],
            [
                'archivedAt' => $this->currentTimestamp(),
            ]
        );

        unset($entries[$remoteId]);

        $this->saveLocalEntries($entries);
        $this->saveArchivedEntries($archived);
        $this->recordSyncMetrics('deleted', 1);

        return true;
    }

    public function getEntryById($id): ?array
    {
        $entries = $this->loadLocalEntries();
        $remoteId = (string) $id;

        return $entries[$remoteId] ?? null;
    }

    public function attachReferenceImage($entryId, $reference): bool
    {
        $remoteId = (string) $entryId;
        $entries = $this->loadLocalEntries();
        $result = false;

        if (!isset($entries[$remoteId]) || !is_array($reference)) {
            return apply_filters('context_alt_text_roster_attach_reference', $result, $entryId, $reference);
        }

        $embeddingRequest = $this->buildEmbeddingRequest($reference);

        if ($embeddingRequest === null) {
            return apply_filters('context_alt_text_roster_attach_reference', $result, $entryId, $reference);
        }

        try {
            $response = $this->client->generateEmbeddings($embeddingRequest);
        } catch (RosterClientException $exception) {
            $this->recordSyncMetrics('errors', 1, $exception);

            return apply_filters('context_alt_text_roster_attach_reference', $result, $entryId, $reference);
        }

        $embedding = $this->extractEmbeddingVector($response);

        if ($embedding === null) {
            return apply_filters('context_alt_text_roster_attach_reference', $result, $entryId, $reference);
        }

        $appendPayload = ['embedding' => $embedding];
        $metadata = $this->extractReferenceMetadata($reference);

        if ($metadata !== []) {
            $appendPayload['metadata'] = $metadata;
        }

        $imagePath = $this->extractImagePath($reference);

        if ($imagePath !== null) {
            $appendPayload['image_path'] = $imagePath;
        }

        try {
            $this->client->appendReferenceEmbedding($remoteId, $appendPayload);
        } catch (RosterClientException $exception) {
            $this->recordSyncMetrics('errors', 1, $exception);

            return apply_filters('context_alt_text_roster_attach_reference', $result, $entryId, $reference);
        }

        $entry = $entries[$remoteId];
        $images = $entry['referenceImages'] ?? [];

        if (!is_array($images)) {
            $images = [];
        }

        $images[] = $this->normalizeReferenceForStorage($reference);
        $entry['referenceImages'] = array_values(
            array_filter(
                $images,
                static fn($item) => is_array($item)
            )
        );
        $entry['updatedAt'] = $this->currentTimestamp();

        $entries[$remoteId] = $entry;
        $this->saveLocalEntries($entries);
        $this->recordSyncMetrics('updated', 1);
        $result = true;

        return apply_filters('context_alt_text_roster_attach_reference', $result, $entryId, $reference);
    }

    public function linkMediaToEntry($entryId, int $attachmentId, array $context = []): void
    {
        $remoteId = (string) $entryId;

        if ($remoteId === '' || $attachmentId <= 0) {
            return;
        }

        $entries = $this->loadLocalEntries();

        if (!isset($entries[$remoteId]) || !is_array($entries[$remoteId])) {
            return;
        }

        $existing = $entries[$remoteId]['media'] ?? [];
        $mediaIndex = [];

        if (is_array($existing)) {
            foreach ($existing as $item) {
                if (!is_array($item)) {
                    continue;
                }

                $existingId = isset($item['attachmentId']) ? (int) $item['attachmentId'] : 0;

                if ($existingId > 0) {
                    $mediaIndex[$existingId] = $item;
                }
            }
        }

        $mediaIndex[$attachmentId] = $this->normalizeMediaAssociation(
            $attachmentId,
            $context,
            $mediaIndex[$attachmentId] ?? []
        );

        $entries[$remoteId]['media'] = array_values($mediaIndex);
        $entries[$remoteId]['mediaCount'] = count($entries[$remoteId]['media']);

        $this->saveLocalEntries($entries);
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

        if ($payload['type'] !== '') {
            $payload['metadata']['type'] = $payload['type'];
        }

        $payload['metadata']['source'] = 'context-alt-text';

        return apply_filters('context_alt_text_roster_payload', $payload, $data, $options);
    }

    /**
     * @param array<string,mixed> $response
     * @param array<string,mixed> $data
     * @param array<string,mixed> $options
     */
    private function persistEntry(array $response, array $data = [], array $options = []): void
    {
        if (isset($options['referenceImages']) && is_array($options['referenceImages'])) {
            $options['referenceImages'] = array_values(
                array_filter(
                    array_map(
                        function ($reference) {
                            if (!is_array($reference)) {
                                return null;
                            }

                            return $this->normalizeReferenceForStorage($reference);
                        },
                        $options['referenceImages']
                    ),
                    static fn($value) => $value !== null
                )
            );
        }

        if (isset($response['entry']) && is_array($response['entry'])) {
            $transformed = $this->transformRemoteEntry($response['entry'], $data, $options);
            $response = array_merge($response, $transformed);
        }

        $entry = $this->normalizeRemoteEntry($response, array_merge($data, $options));

        if (empty($entry['remoteId'])) {
            return;
        }

        $entries = $this->loadLocalEntries();
        $remoteId = $entry['remoteId'];

        if (!isset($entry['referenceImageCount'])) {
            $entry['referenceImageCount'] = isset($entry['referenceImages']) && is_array($entry['referenceImages'])
                ? count($entry['referenceImages'])
                : 0;
        }

        if (!isset($entry['media'])) {
            $existingMedia = $entries[$remoteId]['media'] ?? [];
            if (is_array($existingMedia)) {
                $entry['media'] = $existingMedia;
                $entry['mediaCount'] = $entries[$remoteId]['mediaCount'] ?? count($existingMedia);
            }
        } elseif (!isset($entry['mediaCount'])) {
            $entry['mediaCount'] = is_array($entry['media']) ? count($entry['media']) : 0;
        }

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
        $remoteId = $this->sanitizeNullable($default['id'] ?? $default['remote_id'] ?? $default['unique_id'] ?? $fallback['remoteId'] ?? null);

        $label = $this->sanitizeNullable($default['label'] ?? $default['display_name'] ?? $default['name'] ?? $fallback['label'] ?? null);
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

        $media = [];
        if (isset($default['media']) && is_array($default['media'])) {
            $media = array_values(
                array_filter(
                    $default['media'],
                    static fn($item) => is_array($item)
                )
            );
        } elseif (isset($fallback['media']) && is_array($fallback['media'])) {
            $media = array_values(
                array_filter(
                    $fallback['media'],
                    static fn($item) => is_array($item)
                )
            );
        }

        // Use image_count from API if available, otherwise fallback to counting referenceImages
        $imageCount = 0;
        if (isset($default['image_count']) && is_numeric($default['image_count'])) {
            $imageCount = (int) $default['image_count'];
        } elseif (isset($fallback['referenceImageCount']) && is_numeric($fallback['referenceImageCount'])) {
            $imageCount = (int) $fallback['referenceImageCount'];
        } else {
            $imageCount = is_array($referenceImages) ? count($referenceImages) : 0;
        }

        return [
            'remoteId' => $remoteId,
            'label' => $label,
            'type' => $type,
            'metadata' => $metadata,
            'referenceImages' => $referenceImages,
            'referenceImageCount' => $imageCount,
            'media' => $media,
            'mediaCount' => count($media),
            'updatedAt' => $updatedAt ?: $this->currentTimestamp(),
        ];
    }

    /**
     * @param array<string,mixed> $entry
     * @param array<string,mixed> $data
     * @param array<string,mixed> $options
     * @return array<string,mixed>
     */
    private function transformRemoteEntry(array $entry, array $data, array $options): array
    {
        $referenceImages = [];

        if (isset($entry['reference_images']) && is_array($entry['reference_images'])) {
            foreach ($entry['reference_images'] as $image) {
                if (!is_array($image)) {
                    continue;
                }

                $referenceImages[] = $this->normalizeReferenceForStorage([
                    'image_url' => $image['image_path'] ?? null,
                    'metadata' => $image['metadata'] ?? [],
                ]);
            }
        } elseif (isset($options['referenceImages']) && is_array($options['referenceImages'])) {
            $referenceImages = $options['referenceImages'];
        }

        return [
            'id' => $entry['unique_id'] ?? null,
            'label' => $entry['display_name'] ?? $entry['name'] ?? $data['label'] ?? null,
            'type' => $data['type'] ?? null,
            'metadata' => $entry['metadata'] ?? [],
            'reference_images' => $referenceImages,
            'updated_at' => $entry['updated_timestamp'] ?? $entry['created_timestamp'] ?? null,
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

        $results = [];

        foreach ($options['referenceImages'] as $reference) {
            if (!is_array($reference)) {
                continue;
            }

            $request = $this->buildEmbeddingRequest($reference);

            if ($request === null) {
                continue;
            }

            try {
                $response = $this->client->generateEmbeddings($request);
            } catch (RosterClientException $exception) {
                $this->recordSyncMetrics('errors', 1, $exception);

                continue;
            }

            $embedding = $this->extractEmbeddingVector($response);

            if ($embedding === null) {
                continue;
            }

            $results[] = [
                'embedding' => $embedding,
                'metadata' => $this->extractReferenceMetadata($reference),
                'image_path' => $this->extractImagePath($reference),
            ];
        }

        return $results;
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
     * Attempt to reconcile duplicate create requests by reusing the existing roster entry.
     *
     * @param array<string,mixed> $existing
     * @param array<string,mixed> $data
     * @param array<string,mixed> $options
     */
    private function handleDuplicateCreateRequest(array $existing, array $data, array $options): ?array
    {
        $remoteId = $this->sanitizeNullable($existing['remoteId'] ?? $existing['id'] ?? null);

        if ($remoteId === null || $remoteId === '') {
            $exception = $this->createDuplicateLabelTypeException();
            $this->recordSyncMetrics('errors', 1, $exception);

            return null;
        }

        $hasReferenceImages = !empty($options['referenceImages']) && is_array($options['referenceImages']);

        if ($hasReferenceImages) {
            $result = $this->updateAndSync($remoteId, $data, $options);

            if (is_array($result)) {
                $result['id'] = $result['id'] ?? $remoteId;
                $result['remoteId'] = $result['remoteId'] ?? $remoteId;

                return $result;
            }
        }

        $this->recordSyncMetrics('updated', 0);

        return [
            'id' => $remoteId,
            'remoteId' => $remoteId,
        ];
    }

    /**
     * @return array<string,mixed>|null
     */
    private function findLocalEntryByLabelAndType(string $label, string $type): ?array
    {
        $entries = $this->loadLocalEntries();

        foreach ($entries as $entry) {
            if (!is_array($entry)) {
                continue;
            }

            if (
                isset($entry['label'], $entry['type'])
                && $entry['label'] === $label
                && $entry['type'] === $type
            ) {
                return $entry;
            }
        }

        return null;
    }

    private function buildEmbeddingRequest(array $reference): ?array
    {
        $imagePayload = [];

        $base64 = $reference['image_base64'] ?? $reference['imageBase64'] ?? null;

        if (is_string($base64) && trim($base64) !== '') {
            $encoded = preg_replace('/\s+/', '', $base64);

            if (is_string($encoded) && $encoded !== '') {
                $imagePayload['image_base64'] = $encoded;
            }
        }

        if ($imagePayload === []) {
            $imageUrl = $this->extractImagePath($reference);

            if ($imageUrl !== null) {
                $imagePayload['image_url'] = $imageUrl;
            }
        }

        if ($imagePayload === []) {
            $attachmentId = null;

            foreach (['attachmentId', 'attachment_id'] as $key) {
                if (isset($reference[$key]) && is_numeric($reference[$key])) {
                    $attachmentId = (int) $reference[$key];
                    break;
                }
            }

            if ($attachmentId !== null && function_exists('get_attached_file')) {
                $file = get_attached_file($attachmentId);

                if (is_string($file) && $file !== '' && file_exists($file)) {
                    $contents = file_get_contents($file);

                    if (is_string($contents) && $contents !== '') {
                        $encoded = base64_encode($contents);

                        if ($encoded !== '') {
                            $imagePayload['image_base64'] = $encoded;
                        }
                    }
                }
            }
        }

        if ($imagePayload === []) {
            return null;
        }

        $payload = ['image' => $imagePayload];
        $threshold = $reference['threshold'] ?? null;

        if (is_numeric($threshold)) {
            $payload['threshold'] = (float) $threshold;
        }

        return $payload;
    }

    private function extractEmbeddingVector(array $response): ?array
    {
        if (isset($response['faces']) && is_array($response['faces'])) {
            foreach ($response['faces'] as $face) {
                if (!is_array($face) || !isset($face['embedding']) || !is_array($face['embedding'])) {
                    continue;
                }

                $filtered = array_values(
                    array_filter(
                        $face['embedding'],
                        static fn($value) => is_numeric($value)
                    )
                );

                if ($filtered !== []) {
                    return array_map('floatval', $filtered);
                }
            }
        }

        if (isset($response['vectors']) && is_array($response['vectors'])) {
            $vector = $response['vectors'][0] ?? null;

            if (is_array($vector)) {
                $filtered = array_values(
                    array_filter(
                        $vector,
                        static fn($value) => is_numeric($value)
                    )
                );

                if ($filtered !== []) {
                    return array_map('floatval', $filtered);
                }
            }
        }

        return null;
    }

    private function extractImagePath(array $reference): ?string
    {
        $candidates = [
            $reference['image_path'] ?? null,
            $reference['imagePath'] ?? null,
            $reference['image_url'] ?? null,
            $reference['imageUrl'] ?? null,
            $reference['thumbnail_url'] ?? null,
            $reference['thumbnailUrl'] ?? null,
        ];

        foreach ($candidates as $candidate) {
            if (!is_string($candidate)) {
                continue;
            }

            $url = $this->sanitizeUrl($candidate);

            if ($url !== null) {
                return $url;
            }
        }

        return null;
    }

    private function normalizeMediaAssociation(int $attachmentId, array $context, array $existing = []): array
    {
        $association = $existing;
        $association['attachmentId'] = $attachmentId;

        if (!isset($association['matchedAt'])) {
            $association['matchedAt'] = $context['matchedAt'] ?? $this->currentTimestamp();
        }

        if (isset($context['matchedAt']) && is_string($context['matchedAt'])) {
            $association['matchedAt'] = $context['matchedAt'];
        }

        if (isset($context['observationId']) && is_string($context['observationId'])) {
            $association['observationId'] = $context['observationId'];
        }

        if (!isset($association['title'])) {
            if (isset($context['title']) && is_string($context['title'])) {
                $association['title'] = $context['title'];
            } elseif (function_exists('get_post')) {
                $post = get_post($attachmentId);

                if ($post && isset($post->post_title)) {
                    $association['title'] = (string) $post->post_title;
                }
            }
        }

        if (!isset($association['previewUrl'])) {
            if (isset($context['previewUrl']) && is_string($context['previewUrl'])) {
                $association['previewUrl'] = $context['previewUrl'];
            } elseif (function_exists('wp_get_attachment_url')) {
                $url = wp_get_attachment_url($attachmentId);

                if (is_string($url) && $url !== '') {
                    $association['previewUrl'] = $url;
                }
            }
        }

        if (!isset($association['editUrl'])) {
            if (isset($context['editUrl']) && is_string($context['editUrl'])) {
                $association['editUrl'] = $context['editUrl'];
            } elseif (function_exists('get_edit_post_link')) {
                $editLink = get_edit_post_link($attachmentId, '');

                if (is_string($editLink) && $editLink !== '') {
                    $association['editUrl'] = $editLink;
                }
            }
        }

        if (!isset($association['thumbnailUrl'])) {
            if (isset($context['thumbnailUrl']) && is_string($context['thumbnailUrl'])) {
                $association['thumbnailUrl'] = $context['thumbnailUrl'];
            } elseif (function_exists('wp_get_attachment_image_url')) {
                $thumb = wp_get_attachment_image_url($attachmentId, 'thumbnail');

                if (is_string($thumb) && $thumb !== '') {
                    $association['thumbnailUrl'] = $thumb;
                }
            }
        }

        return $association;
    }

    private function extractReferenceMetadata(array $reference): array
    {
        if (isset($reference['metadata']) && is_array($reference['metadata'])) {
            return $reference['metadata'];
        }

        return [];
    }

    private function normalizeReferenceForStorage(array $reference): array
    {
        $normalized = [];

        foreach (['image_url', 'imageUrl', 'thumbnail_url', 'thumbnailUrl'] as $key) {
            if (!isset($reference[$key]) || !is_string($reference[$key])) {
                continue;
            }

            $url = $this->sanitizeUrl((string) $reference[$key]);

            if ($url !== null) {
                $normalized[$key] = $url;
            }
        }

        foreach (['attachment_id', 'attachmentId'] as $key) {
            if (!isset($reference[$key]) || !is_numeric($reference[$key])) {
                continue;
            }

            $normalized[$key] = (int) $reference[$key];
        }

        $metadata = $this->extractReferenceMetadata($reference);

        if ($metadata !== []) {
            $normalized['metadata'] = $metadata;
        }

        $normalized['syncedAt'] = $this->currentTimestamp();

        return $normalized;
    }

    /**
     * @param array<int,array{embedding:array<int,float>,metadata:array<string,mixed>,image_path:?string}> $embeddings
     * @return array<int,array<string,mixed>>
     */
    private function mapEmbeddingsForPayload(array $embeddings): array
    {
        return array_map(
            static function (array $row): array {
                $payload = [
                    'embedding' => $row['embedding'],
                ];

                if (!empty($row['metadata'])) {
                    $payload['metadata'] = $row['metadata'];
                }

                if (!empty($row['image_path'])) {
                    $payload['image_path'] = $row['image_path'];
                }

                return $payload;
            },
            $embeddings
        );
    }

    private function sanitizeUrl(string $value): ?string
    {
        $trimmed = trim($value);

        if ($trimmed === '') {
            return null;
        }

        if (function_exists('esc_url_raw')) {
            $sanitized = call_user_func('esc_url_raw', $trimmed);

            if (is_string($sanitized) && $sanitized !== '') {
                return $sanitized;
            }
        }

        return $trimmed;
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

    /**
     * Create a new roster person
     *
     * @param string $displayName The person's display name
     * @return string The roster person ID
     * @throws RosterClientException
     */
    public function createPerson(string $displayName): string
    {
        // Create via remote API
        $response = $this->client->createPerson([
            'display' => $displayName,
            'type' => 'person',
        ]);

        $rosterId = $response['rosterId'] ?? null;
        if (!is_string($rosterId) || trim($rosterId) === '') {
            throw new RosterClientException('Failed to create roster person: invalid response');
        }

        // Sync local roster
        $this->syncFromRemote();

        return $rosterId;
    }

    /**
     * Create an observation for a face
     *
     * @param int $attachmentId The WordPress attachment ID
     * @param array<float> $embedding The face embedding
     * @param string $rosterId The roster person ID
     * @param array<string,float> $bbox The bounding box coordinates
     * @return int The observation ID
     * @throws RosterClientException
     */
    public function createObservation(
        int $attachmentId,
        array $embedding,
        string $rosterId,
        array $bbox
    ): int {
        // Create via remote API
        $response = $this->client->createObservation([
            'attachmentId' => $attachmentId,
            'embedding' => $embedding,
            'rosterId' => $rosterId,
            'bbox' => $bbox,
        ]);

        $observationId = $response['observationId'] ?? null;
        if (!is_int($observationId) || $observationId <= 0) {
            throw new RosterClientException('Failed to create observation: invalid response');
        }

        return $observationId;
    }
}
