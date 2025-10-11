<?php

declare(strict_types=1);

namespace ContextAltText\Recognition;

use function array_filter;
use function array_intersect_key;
use function array_key_exists;
use function array_map;
use function array_slice;
use function array_values;
use function count;
use function get_post_meta;
use function in_array;
use function is_array;
use function is_numeric;
use function is_scalar;
use function max;
use function sanitize_text_field;
use function time;
use function update_post_meta;

class RecognitionObservationRepository
{
    private const META_KEY = '_context_alt_text_recognition_observations';

    /**
     * @param array<string,mixed> $payload
     */
    public function store(int $attachmentId, array $payload): void
    {
        $normalized = $this->normalizePayload($payload, $attachmentId);
        update_post_meta($attachmentId, self::META_KEY, $normalized);
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
            ];
        }

        return $this->normalizePayload($stored, $attachmentId, false);
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

        foreach ([
            'remoteId' => 'remoteId',
            'name' => 'name',
            'displayName' => 'displayName',
            'type' => 'type',
        ] as $key => $sourceKey) {
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
}
