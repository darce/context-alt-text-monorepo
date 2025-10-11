<?php

declare(strict_types=1);

namespace ContextAltText\Recognition;

use function __;
use function apply_filters;
use function array_filter;
use function array_map;
use function array_slice;
use function array_unique;
use function array_values;
use function basename;
use function current_user_can;
use function do_action;
use function get_post;
use function get_post_mime_type;
use function is_array;
use function is_numeric;
use function is_scalar;
use function max;
use function sprintf;
use function sanitize_text_field;
use function strtolower;
use function strpos;
use function time;
use function wp_json_encode;
use function wp_get_attachment_url;

class RecognitionJobService
{
    private RecognitionClient $client;
    private RecognitionJobRepository $repository;
    private RecognitionObservationRepository $observations;

    public function __construct(
        RecognitionClient $client,
        RecognitionJobRepository $repository,
        RecognitionObservationRepository $observations
    ) {
        $this->client = $client;
        $this->repository = $repository;
        $this->observations = $observations;
    }

    /**
     * @param array<int|numeric-string> $attachmentIds
     *
     * @return array<string,mixed>
     */
    public function submit(array $attachmentIds): array
    {
        $normalizedIds = $this->normalizeAttachmentIds($attachmentIds);

        $accepted = [];
        $rejected = [];

        foreach ($normalizedIds as $attachmentId) {
            if ($attachmentId <= 0) {
                $rejected[] = $attachmentId;
                continue;
            }

            if (!current_user_can('edit_post', $attachmentId)) {
                $rejected[] = $attachmentId;
                continue;
            }

            $post = get_post($attachmentId);

            if (!$post || $post->post_type !== 'attachment') {
                $rejected[] = $attachmentId;
                continue;
            }

            $mime = get_post_mime_type($attachmentId);
            if (!$mime || strtolower((string) $mime) === '' || strpos((string) $mime, 'image/') !== 0) {
                $rejected[] = $attachmentId;
                continue;
            }

            $url = wp_get_attachment_url($attachmentId);
            if (!$url) {
                $rejected[] = $attachmentId;
                continue;
            }

            $accepted[] = [
                'id' => $attachmentId,
                'image_url' => $url,
                'filename' => basename($url),
            ];
        }

        if (empty($accepted)) {
            return [
                'job' => null,
                'accepted' => 0,
                'rejected' => $rejected,
                'status' => 'rejected',
                'message' => __('No valid attachments were provided for recognition.', 'context-alt-text'),
            ];
        }

        $job = $this->repository->create([
            'attachments' => array_map(static fn(array $item): array => [
                'id' => $item['id'],
                'imageUrl' => $item['image_url'],
                'filename' => $item['filename'],
            ], $accepted),
            'rejected' => $rejected,
        ]);

        $job['status'] = 'processing';
        $job['startedAt'] = time();
        $this->repository->save($job);

        try {
            $payload = [
                'images' => array_map(static fn(array $item): array => [
                    'filename' => sanitize_text_field($item['filename']),
                    'image_url' => $item['image_url'],
                ], $accepted),
                'use_roster' => true,
            ];

            $response = $this->client->analyzeScene($payload);

            $job['status'] = 'complete';
            $job['result'] = $response;
            $job['completedAt'] = time();
            $this->repository->save($job);
            $this->persistObservations($job, $accepted, $response);
        } catch (RecognitionClientException $exception) {
            $job['status'] = 'error';
            $job['error'] = $exception->getMessage();
            $job['completedAt'] = null;
            $this->repository->save($job);
            $this->logFailure($job, $exception);
        }

        return [
            'job' => $job,
            'jobId' => $job['id'],
            'status' => $job['status'],
            'accepted' => count($accepted),
            'rejected' => $rejected,
        ];
    }

    /**
     * @return array<string,mixed>|null
     */
    public function getJob(string $jobId): ?array
    {
        $job = $this->repository->find($jobId);

        if ($job === null) {
            return null;
        }

        $job['observations'] = $this->hydrateAttachmentObservations($job);

        return $job;
    }

    /**
     * @param array<int|numeric-string> $ids
     * @return array<int>
     */
    private function normalizeAttachmentIds(array $ids): array
    {
        $filtered = array_filter($ids, static fn($value) => is_scalar($value) || $value === 0 || $value === '0');

        $ints = array_map(static fn($value): int => (int) $value, $filtered);

        return array_values(array_unique($ints));
    }

    /**
     * @param array<string,mixed> $job
     */
    private function logFailure(array $job, RecognitionClientException $exception): void
    {
        $context = [
            'jobId' => $job['id'] ?? null,
            'status' => $job['status'] ?? null,
            'attachments' => array_map(
                static fn(array $item) => $item['id'] ?? null,
                isset($job['attachments']) && is_array($job['attachments']) ? $job['attachments'] : []
            ),
            'error' => $exception->getMessage(),
        ];

        do_action('cat_recognition_job_failed', $context, $exception);

        $message = sprintf(
            '[context-alt-text] Recognition job %s failed',
            isset($context['jobId']) && $context['jobId'] !== null ? (string) $context['jobId'] : 'unknown'
        );

        $shouldLog = apply_filters('cat_recognition_should_log_error', true, $context, $exception);

        if ($shouldLog) {
            \error_log($message . ' ' . wp_json_encode($context));
        }
    }

    /**
     * @param array<string,mixed> $job
     * @param array<int,array{id:int,image_url:string,filename:string}> $accepted
     * @param array<string,mixed> $response
     */
    private function persistObservations(array $job, array $accepted, array $response): void
    {
        if (!isset($response['results']) || !is_array($response['results'])) {
            return;
        }

        $results = array_values($response['results']);

        foreach ($accepted as $index => $attachment) {
            $result = $results[$index] ?? null;
            $attachmentId = (int) ($attachment['id'] ?? 0);

            if ($attachmentId <= 0) {
                continue;
            }

            $observations = [];

            if (is_array($result)) {
                $observations = $this->mapDetectedEntities(
                    (string) ($job['id'] ?? ''),
                    $index,
                    $result
                );
            }

            $summary = $this->calculateSummary($observations);

            $payload = [
                'jobId' => $job['id'] ?? null,
                'attachmentId' => $attachmentId,
                'updatedAt' => $job['completedAt'] ?? time(),
                'observations' => $observations,
                'summary' => $summary,
                'context' => [
                    'filename' => $attachment['filename'] ?? '',
                    'imageUrl' => $attachment['image_url'] ?? '',
                ],
            ];

            $this->observations->store($attachmentId, $payload);

            do_action(
                'cat_recognition_observations_stored',
                $job['id'] ?? null,
                $attachmentId,
                $payload
            );
        }
    }

    /**
     * @param array<string,mixed> $job
     * @return array<int,array<string,mixed>>
     */
    private function hydrateAttachmentObservations(array $job): array
    {
        if (!isset($job['attachments']) || !is_array($job['attachments'])) {
            return [];
        }

        $observations = [];

        foreach ($job['attachments'] as $attachment) {
            if (!is_array($attachment)) {
                continue;
            }

            $attachmentId = isset($attachment['id']) && is_numeric($attachment['id'])
                ? (int) $attachment['id']
                : null;

            if ($attachmentId === null || $attachmentId <= 0) {
                continue;
            }

            $observations[] = $this->observations->get($attachmentId);
        }

        return $observations;
    }

    /**
     * @param array<string,mixed> $result
     * @return array<int,array<string,mixed>>
     */
    private function mapDetectedEntities(string $jobId, int $attachmentIndex, array $result): array
    {
        if (!isset($result['detected_entities']) || !is_array($result['detected_entities'])) {
            return [];
        }

        $entities = array_values($result['detected_entities']);
        $observations = [];

        foreach ($entities as $entityIndex => $entity) {
            if (!is_array($entity)) {
                continue;
            }

            $match = $this->extractMatch($entity['roster_match'] ?? null);
            $roster = $this->extractRoster($entity['roster_match']['roster_entry'] ?? null);
            $status = $match['isMatch'] && $roster !== null ? 'matched' : 'needs_review';

            $observations[] = [
                'observationId' => sprintf('%s-%d-%d', $jobId !== '' ? $jobId : 'job', $attachmentIndex, $entityIndex),
                'label' => sanitize_text_field((string) ($entity['label'] ?? '')),
                'entityType' => sanitize_text_field((string) ($entity['entity_type'] ?? '')),
                'confidence' => $this->normalizeFloat($entity['confidence'] ?? 0.0),
                'area' => $this->normalizeFloat($entity['area'] ?? 0.0),
                'boundingBox' => $this->normalizeBoundingBox($entity['bbox'] ?? []),
                'status' => $status,
                'source' => 'recognition-service',
                'match' => $match,
                'roster' => $roster,
                'candidates' => $this->extractCandidates($entity['face_data']['candidates'] ?? []),
            ];
        }

        return $observations;
    }

    /**
     * @param array<int,mixed> $box
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
     * @param mixed $match
     * @return array<string,mixed>
     */
    private function extractMatch($match): array
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
            'isMatch' => !empty($match['is_match']) || !empty($match['isMatch']),
            'similarity' => $this->normalizeFloat($match['similarity_score'] ?? $match['similarity'] ?? 0.0),
            'confidence' => $this->normalizeFloat($match['match_confidence'] ?? $match['confidence'] ?? 0.0),
            'threshold' => $this->normalizeFloat($match['confidence_threshold'] ?? $match['threshold'] ?? 0.0),
        ];
    }

    /**
     * @param mixed $roster
     * @return array<string,string>|null
     */
    private function extractRoster($roster): ?array
    {
        if (!is_array($roster)) {
            return null;
        }

        $result = [];

        if (isset($roster['unique_id']) && is_scalar($roster['unique_id'])) {
            $result['remoteId'] = sanitize_text_field((string) $roster['unique_id']);
        } elseif (isset($roster['remoteId']) && is_scalar($roster['remoteId'])) {
            $result['remoteId'] = sanitize_text_field((string) $roster['remoteId']);
        }

        if (isset($roster['display_name']) && is_scalar($roster['display_name'])) {
            $result['displayName'] = sanitize_text_field((string) $roster['display_name']);
        } elseif (isset($roster['displayName']) && is_scalar($roster['displayName'])) {
            $result['displayName'] = sanitize_text_field((string) $roster['displayName']);
        }

        if (isset($roster['name']) && is_scalar($roster['name'])) {
            $result['name'] = sanitize_text_field((string) $roster['name']);
        }

        if (isset($roster['metadata']['type']) && is_scalar($roster['metadata']['type'])) {
            $result['type'] = sanitize_text_field((string) $roster['metadata']['type']);
        } elseif (isset($roster['type']) && is_scalar($roster['type'])) {
            $result['type'] = sanitize_text_field((string) $roster['type']);
        }

        return $result ?: null;
    }

    /**
     * @param mixed $candidates
     * @return array<int,array<string,mixed>>
     */
    private function extractCandidates($candidates): array
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
                'remoteId' => sanitize_text_field((string) ($candidate['unique_id'] ?? $candidate['remoteId'] ?? '')),
                'name' => sanitize_text_field((string) ($candidate['name'] ?? '')),
                'similarity' => $this->normalizeFloat($candidate['similarity'] ?? 0.0),
                'meetsThreshold' => !empty($candidate['meets_threshold']) || !empty($candidate['meetsThreshold']),
            ];
        }

        return $normalized;
    }

    /**
     * @param array<int,array<string,mixed>> $observations
     * @return array<string,int>
     */
    private function calculateSummary(array $observations): array
    {
        $matched = 0;
        $total = count($observations);

        foreach ($observations as $observation) {
            if (($observation['status'] ?? '') === 'matched') {
                $matched++;
            }
        }

        return [
            'total' => $total,
            'matched' => $matched,
            'needs_review' => max(0, $total - $matched),
        ];
    }
}
