<?php

declare(strict_types=1);

namespace ContextAltText\Recognition;

use function array_filter;
use function array_flip;
use function array_intersect_key;
use function array_key_exists;
use function array_map;
use function array_slice;
use function array_values;
use function array_unique;
use function count;
use function function_exists;
use function get_post_meta;
use function get_option;
use function in_array;
use function is_array;
use function is_numeric;
use function is_scalar;
use function max;
use function mb_strtolower;
use function sanitize_text_field;
use function sanitize_title;
use function time;
use function update_post_meta;
use function str_starts_with;
use function term_exists;
use function wp_get_object_terms;
use function wp_insert_term;
use function wp_set_post_terms;
use function is_wp_error;
use function sprintf;

class RecognitionObservationRepository
{
    private const META_KEY = '_context_alt_text_recognition_observations';
    private const INDEX_OPTION = 'cat_recognition_observation_index';
    private const TAG_TAXONOMY = 'post_tag';
    private const TAG_PREFIX = 'cat-recognition-';

    /**
     * @param array<string,mixed> $payload
     */
    public function store(int $attachmentId, array $payload): void
    {
        $normalized = $this->normalizePayload($payload, $attachmentId);
        update_post_meta($attachmentId, self::META_KEY, $normalized);
        $this->touchIndex($attachmentId, $normalized['updatedAt'] ?? time());
        $this->syncAttachmentTags($attachmentId, $normalized['observations']);
    }

    /**
     * @return array<string,mixed>
     */
    public function get(int $attachmentId): array
    {
        $stored = get_post_meta($attachmentId, self::META_KEY, true);

        if (!is_array($stored)) {
            return [
                'jobId' => null,
                'attachmentId' => $attachmentId,
                'updatedAt' => null,
                'observations' => [],
                'summary' => [
                    'total' => 0,
                    'matched' => 0,
                    'needs_review' => 0,
                ],
                'context' => [],
                'confidenceScore' => 0.0,
                'sourceRemoteId' => null,
            ];
        }

        return $this->normalizePayload($stored, $attachmentId, false);
    }

    /**
     * @return array<int>
     */
    public function getRecentAttachmentIds(int $limit = 20, int $offset = 0): array
    {
        $limit = max(1, min(100, $limit));
        $offset = max(0, $offset);

        if (!function_exists('get_option')) {
            return [];
        }

        $stored = get_option(self::INDEX_OPTION, []);

        if (!is_array($stored)) {
            return [];
        }

        arsort($stored);

        $ids = [];
        foreach (array_slice($stored, $offset, $limit, true) as $attachmentId => $updatedAt) {
            $ids[] = (int) $attachmentId;
        }

        return $ids;
    }

    /**
     * @param string|null $entityType
     * @param array<int> $excludeAttachmentIds
     * @return array<int>
     */
    public function findAttachmentIdsNeedingReview(?string $entityType = null, int $limit = 20, array $excludeAttachmentIds = []): array
    {
        $limit = max(1, min(100, $limit));

        if (!function_exists('get_option')) {
            return [];
        }

        $stored = get_option(self::INDEX_OPTION, []);

        if (!is_array($stored)) {
            return [];
        }

        arsort($stored);

        $normalizedType = null;

        if ($entityType !== null) {
            $candidate = sanitize_text_field($entityType);
            if ($candidate !== '') {
                $normalizedType = mb_strtolower($candidate);
            }
        }

        $exclude = [];
        foreach ($excludeAttachmentIds as $value) {
            $attachmentId = (int) $value;
            if ($attachmentId > 0) {
                $exclude[$attachmentId] = true;
            }
        }

        $ids = [];

        foreach ($stored as $attachmentId => $_updatedAt) {
            if (count($ids) >= $limit) {
                break;
            }

            $attachmentId = (int) $attachmentId;

            if ($attachmentId <= 0 || isset($exclude[$attachmentId])) {
                continue;
            }

            $record = $this->get($attachmentId);

            if (($record['summary']['needs_review'] ?? 0) <= 0) {
                continue;
            }

            if ($normalizedType !== null && !$this->recordMatchesEntityType($record, $normalizedType)) {
                continue;
            }

            $ids[] = $attachmentId;
        }

        return $ids;
    }

    /**
     * @param array<int> $attachmentIds
     * @return array<int,array<string,mixed>>
     */
    public function getMany(array $attachmentIds): array
    {
        $records = [];

        foreach ($attachmentIds as $attachmentId) {
            $attachmentId = (int) $attachmentId;

            if ($attachmentId <= 0) {
                continue;
            }

            $records[] = $this->get($attachmentId);
        }

        return $records;
    }

    /**
     * @param array<string,mixed> $updates
     * @return array<string,mixed>|null
     */
    public function updateObservation(int $attachmentId, string $observationId, array $updates): ?array
    {
        $observationId = sanitize_text_field($observationId);

        if ($observationId === '') {
            return null;
        }

        $current = $this->get($attachmentId);
        $observations = $current['observations'] ?? [];

        foreach ($observations as $index => $observation) {
            if (!is_array($observation)) {
                continue;
            }

            if (($observation['observationId'] ?? '') !== $observationId) {
                continue;
            }

            unset($updates['observationId']);

            $allowed = array_intersect_key(
                $updates,
                array_flip([
                    'status',
                    'label',
                    'entityType',
                    'confidence',
                    'area',
                    'boundingBox',
                    'source',
                    'match',
                    'roster',
                    'candidates',
                ])
            );

            $merged = array_merge($observation, $allowed);
            $observations[$index] = $this->normalizeObservation($merged);

            $this->store($attachmentId, [
                'jobId' => $current['jobId'] ?? null,
                'attachmentId' => $attachmentId,
                'observations' => $observations,
                'context' => $current['context'] ?? [],
                'confidenceScore' => $current['confidenceScore'] ?? 0.0,
                'sourceRemoteId' => $current['sourceRemoteId'] ?? null,
            ]);
            $this->syncAttachmentTags($attachmentId, $observations);

            return $this->get($attachmentId);
        }

        return null;
    }

    /**
     * @param array<string,mixed> $payload
     * @return array<string,mixed>
     */
    private function normalizePayload(array $payload, int $attachmentId, bool $refreshTimestamp = true): array
    {
        $jobId = isset($payload['jobId']) && is_scalar($payload['jobId'])
            ? sanitize_text_field((string) $payload['jobId'])
            : null;

        $observations = [];

        if (isset($payload['observations']) && is_array($payload['observations'])) {
            $observations = array_values(array_map(
                fn($item) => $this->normalizeObservation($item),
                array_filter($payload['observations'], static fn($item) => is_array($item))
            ));
        }

        $matched = 0;
        foreach ($observations as $observation) {
            if (($observation['status'] ?? '') === 'matched') {
                $matched++;
            }
        }

        $total = count($observations);
        $needsReview = max(0, $total - $matched);

        $summary = [
            'total' => $total,
            'matched' => $matched,
            'needs_review' => $needsReview,
        ];

        if (isset($payload['summary']) && is_array($payload['summary'])) {
            $summary = array_merge($summary, array_intersect_key($payload['summary'], $summary));
        }

        $context = [];
        if (isset($payload['context']) && is_array($payload['context'])) {
            foreach (['filename', 'imageUrl'] as $key) {
                if (array_key_exists($key, $payload['context']) && is_scalar($payload['context'][$key])) {
                    $context[$key] = sanitize_text_field((string) $payload['context'][$key]);
                }
            }
        }

        $updatedAt = $refreshTimestamp
            ? time()
            : (isset($payload['updatedAt']) && is_numeric($payload['updatedAt'])
                ? (int) $payload['updatedAt']
                : null);

        if ($refreshTimestamp && isset($payload['updatedAt']) && is_numeric($payload['updatedAt'])) {
            $updatedAt = (int) $payload['updatedAt'];
        }

        $confidenceScore = $this->normalizeFloat($payload['confidenceScore'] ?? 0.0);
        $sourceRemoteId = $this->normalizeOptionalString($payload['sourceRemoteId'] ?? null);

        return [
            'jobId' => $jobId,
            'attachmentId' => $attachmentId,
            'updatedAt' => $updatedAt,
            'observations' => $observations,
            'summary' => [
                'total' => (int) $summary['total'],
                'matched' => (int) $summary['matched'],
                'needs_review' => (int) $summary['needs_review'],
            ],
            'context' => $context,
            'confidenceScore' => $confidenceScore,
            'sourceRemoteId' => $sourceRemoteId,
        ];
    }

    /**
     * @param array<string,mixed> $observation
     * @return array<string,mixed>
     */
    private function normalizeObservation(array $observation): array
    {
        $status = $this->normalizeStatus($observation['status'] ?? null);

        return [
            'observationId' => $this->normalizeString($observation['observationId'] ?? null),
            'label' => $this->normalizeString($observation['label'] ?? ''),
            'entityType' => $this->normalizeString($observation['entityType'] ?? ''),
            'confidence' => $this->normalizeFloat($observation['confidence'] ?? 0.0),
            'area' => $this->normalizeFloat($observation['area'] ?? 0.0),
            'boundingBox' => $this->normalizeBoundingBox($observation['boundingBox'] ?? []),
            'status' => $status,
            'source' => $this->normalizeSource($observation['source'] ?? null),
            'match' => $this->normalizeMatch($observation['match'] ?? []),
            'roster' => $this->normalizeRoster($observation['roster'] ?? null),
            'candidates' => $this->normalizeCandidates($observation['candidates'] ?? []),
        ];
    }

    private function normalizeStatus($status): string
    {
        if (!is_scalar($status)) {
            return 'needs_review';
        }

        $value = (string) $status;

        if (!in_array($value, ['matched', 'needs_review'], true)) {
            return 'needs_review';
        }

        return $value;
    }

    private function normalizeString($value): string
    {
        if (!is_scalar($value)) {
            return '';
        }

        return sanitize_text_field((string) $value);
    }

    private function normalizeOptionalString($value): ?string
    {
        if (!is_scalar($value)) {
            return null;
        }

        $sanitized = sanitize_text_field((string) $value);

        return $sanitized !== '' ? $sanitized : null;
    }

    /**
     * @param mixed $value
     */
    private function normalizeFloat($value): float
    {
        if (is_numeric($value)) {
            return (float) $value;
        }

        return 0.0;
    }

    /**
     * @param mixed $box
     * @return array<int,float>
     */
    private function normalizeBoundingBox($box): array
    {
        if (!is_array($box)) {
            return [];
        }

        $normalized = [];

        foreach (array_slice($box, 0, 4) as $value) {
            $normalized[] = $this->normalizeFloat($value);
        }

        return $normalized;
    }

    /**
     * @param mixed $match
     * @return array<string,mixed>
     */
    private function normalizeMatch($match): array
    {
        if (!is_array($match)) {
            return [
                'isMatch' => false,
                'similarity' => 0.0,
                'confidence' => 0.0,
                'threshold' => 0.0,
            ];
        }

        return [
            'isMatch' => !empty($match['isMatch']),
            'similarity' => $this->normalizeFloat($match['similarity'] ?? 0.0),
            'confidence' => $this->normalizeFloat($match['confidence'] ?? 0.0),
            'threshold' => $this->normalizeFloat($match['threshold'] ?? 0.0),
        ];
    }

    /**
     * @param mixed $roster
     * @return array<string,string>|null
     */
    private function normalizeRoster($roster): ?array
    {
        if (!is_array($roster)) {
            return null;
        }

        $result = [];

        foreach (
            [
                'remoteId' => 'remoteId',
                'name' => 'name',
                'displayName' => 'displayName',
                'type' => 'type',
            ] as $key => $sourceKey
        ) {
            if (array_key_exists($sourceKey, $roster) && is_scalar($roster[$sourceKey])) {
                $result[$key] = sanitize_text_field((string) $roster[$sourceKey]);
            }
        }

        return $result ?: null;
    }

    /**
     * @param mixed $candidates
     * @return array<int,array<string,mixed>>
     */
    private function normalizeCandidates($candidates): array
    {
        if (!is_array($candidates)) {
            return [];
        }

        $normalized = [];

        foreach (array_slice($candidates, 0, 10) as $candidate) {
            if (!is_array($candidate)) {
                continue;
            }

            $normalized[] = [
                'remoteId' => $this->normalizeString($candidate['remoteId'] ?? ($candidate['unique_id'] ?? '')),
                'name' => $this->normalizeString($candidate['name'] ?? ''),
                'similarity' => $this->normalizeFloat($candidate['similarity'] ?? 0.0),
                'meetsThreshold' => !empty($candidate['meetsThreshold']) || !empty($candidate['meets_threshold']),
                'confidence' => $this->normalizeFloat($candidate['confidence'] ?? ($candidate['similarity'] ?? 0.0)),
            ];
        }

        return $normalized;
    }

    private function normalizeSource($source): string
    {
        if (!is_scalar($source) || $source === '') {
            return 'recognition-service';
        }

        return sanitize_text_field((string) $source);
    }

    private function touchIndex(int $attachmentId, ?int $updatedAt): void
    {
        if (!function_exists('get_option') || !function_exists('update_option')) {
            return;
        }

        $updatedAt = $updatedAt ?? time();

        $index = get_option(self::INDEX_OPTION, []);

        if (!is_array($index)) {
            $index = [];
        }

        $index[(string) $attachmentId] = (int) $updatedAt;

        arsort($index);
        $slice = array_slice($index, 0, 100, true);

        update_option(self::INDEX_OPTION, $slice);
    }

    /**
     * @param array<string,mixed> $record
     */
    private function recordMatchesEntityType(array $record, string $entityType): bool
    {
        if (!isset($record['observations']) || !is_array($record['observations'])) {
            return false;
        }

        foreach ($record['observations'] as $observation) {
            if (!is_array($observation) || ($observation['status'] ?? '') !== 'needs_review') {
                continue;
            }

            $type = '';

            if (isset($observation['entityType']) && is_scalar($observation['entityType'])) {
                $type = sanitize_text_field((string) $observation['entityType']);
            } elseif (isset($observation['type']) && is_scalar($observation['type'])) {
                $type = sanitize_text_field((string) $observation['type']);
            }

            if ($type !== '' && mb_strtolower($type) === $entityType) {
                return true;
            }
        }

        return false;
    }

    private function syncAttachmentTags(int $attachmentId, array $observations): void
    {
        if (
            !function_exists('wp_get_object_terms')
            || !function_exists('wp_set_post_terms')
            || !function_exists('wp_insert_term')
            || !function_exists('term_exists')
        ) {
            return;
        }

        $targets = [];

        foreach ($observations as $observation) {
            if (!is_array($observation) || ($observation['status'] ?? '') !== 'matched') {
                continue;
            }

            $roster = isset($observation['roster']) && is_array($observation['roster'])
                ? $observation['roster']
                : null;

            if ($roster === null) {
                continue;
            }

            $remoteId = isset($roster['remoteId']) && is_scalar($roster['remoteId'])
                ? sanitize_text_field((string) $roster['remoteId'])
                : '';

            if ($remoteId === '') {
                continue;
            }

            $label = '';
            foreach (['displayName', 'name'] as $labelKey) {
                if (isset($roster[$labelKey]) && is_scalar($roster[$labelKey])) {
                    $label = sanitize_text_field((string) $roster[$labelKey]);
                    break;
                }
            }

            if ($label === '') {
                $label = isset($observation['label']) && is_scalar($observation['label'])
                    ? sanitize_text_field((string) $observation['label'])
                    : $remoteId;
            }

            $slugBase = sanitize_title($remoteId);

            if ($slugBase === '') {
                $slugBase = sanitize_title($label);
            }

            if ($slugBase === '') {
                $slugBase = substr(md5($remoteId), 0, 10);
            }

            $slug = self::TAG_PREFIX . $slugBase;

            $targets[$slug] = [
                'name' => $label,
                'remoteId' => $remoteId,
            ];
        }

        $existingTerms = wp_get_object_terms(
            $attachmentId,
            self::TAG_TAXONOMY,
            [
                'fields' => 'all',
            ]
        );

        $existingManagedIds = [];
        $otherTermIds = [];

        if (is_array($existingTerms)) {
            foreach ($existingTerms as $term) {
                $termId = is_object($term)
                    ? (int) ($term->term_id ?? 0)
                    : (int) ($term['term_id'] ?? 0);
                $slug = is_object($term)
                    ? (string) ($term->slug ?? '')
                    : (string) ($term['slug'] ?? '');

                if ($termId <= 0) {
                    continue;
                }

                if ($slug !== '' && str_starts_with($slug, self::TAG_PREFIX)) {
                    $existingManagedIds[$slug] = $termId;
                    continue;
                }

                $otherTermIds[] = $termId;
            }
        }

        $managedIds = [];

        foreach ($targets as $slug => $info) {
            $termId = $existingManagedIds[$slug] ?? 0;

            if ($termId <= 0) {
                $term = term_exists($slug, self::TAG_TAXONOMY);
                if ($term && !is_wp_error($term)) {
                    if (is_array($term)) {
                        $termId = (int) ($term['term_id'] ?? 0);
                    } elseif (is_numeric($term)) {
                        $termId = (int) $term;
                    }
                }
            }

            if ($termId <= 0) {
                $result = wp_insert_term(
                    $info['name'],
                    self::TAG_TAXONOMY,
                    [
                        'slug' => $slug,
                        'description' => sprintf('Recognition match for %s', $info['remoteId']),
                    ]
                );

                if (is_wp_error($result)) {
                    continue;
                }

                if (is_array($result) && isset($result['term_id'])) {
                    $termId = (int) $result['term_id'];
                }
            }

            if ($termId > 0) {
                $managedIds[] = $termId;
            }
        }

        if ($managedIds === [] && $existingManagedIds === []) {
            return;
        }

        $finalIds = array_values(array_unique(array_merge($otherTermIds, $managedIds)));
        wp_set_post_terms($attachmentId, $finalIds, self::TAG_TAXONOMY, false);

        if (function_exists('update_post_meta')) {
            $remoteIds = array_values(
                array_unique(
                    array_map(
                        static fn(array $info): string => $info['remoteId'],
                        $targets
                    )
                )
            );

            update_post_meta($attachmentId, '_cat_recognition_roster_ids', $remoteIds);
        }
    }

}
