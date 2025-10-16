<?php

declare(strict_types=1);

namespace ContextAltText\Recognition;

use ContextAltText\Roster\RosterObservationManager;
use function __;
use function add_action;
use function apply_filters;
use function array_filter;
use function array_map;
use function array_slice;
use function array_unique;
use function array_values;
use function basename;
use function current_user_can;
use function do_action;
use function function_exists;
use function get_attached_file;
use function get_option;
use function get_post;
use function get_post_mime_type;
use function update_option;
use function file_exists;
use function file_get_contents;
use function base64_encode;
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
use function wp_next_scheduled;
use function wp_schedule_single_event;

class RecognitionJobService
{
    public const PROCESS_HOOK = 'context_alt_text_process_recognition_job';
    private const JOB_RETRY_DELAY = 1;
    private const RETRY_COOLDOWN_SECONDS = 300;
    private const RETRY_LOG_OPTION = 'cat_recognition_retry_log';
    private const MAX_BATCH_SIZE = 5;

    /**
     * @var array<int,int>
     */
    private array $retryLogFallback = [];

    private RecognitionClient $client;
    private RecognitionJobRepository $repository;
    private RecognitionObservationRepository $observations;
    private ?RosterObservationManager $rosterObservationManager = null;

    public function __construct(
        RecognitionClient $client,
        RecognitionJobRepository $repository,
        RecognitionObservationRepository $observations
    ) {
        $this->client = $client;
        $this->repository = $repository;
        $this->observations = $observations;
        add_action(self::PROCESS_HOOK, [$this, 'processJob'], 10, 1);
    }

    public function setRosterObservationManager(RosterObservationManager $manager): void
    {
        $this->rosterObservationManager = $manager;
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

        [$eligible, $deferred] = $this->filterEligibleAttachments($accepted);

        if ($eligible === []) {
            return [
                'job' => null,
                'jobId' => null,
                'status' => 'deferred',
                'accepted' => 0,
                'rejected' => $rejected,
                'deferred' => $deferred,
            ];
        }

        $job = $this->repository->create([
            'attachments' => $eligible,
            'rejected' => $rejected,
        ]);
        $this->repository->save($job);
        $this->dispatchJob((string) $job['id']);

        return [
            'job' => $job,
            'jobId' => $job['id'],
            'status' => 'queued',
            'accepted' => count($eligible),
            'rejected' => $rejected,
            'deferred' => $deferred,
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
     * Background processor hooked to {@see self::PROCESS_HOOK}.
     *
     * @param string $jobId
     */
    public function processJob($jobId): void
    {
        if (!is_string($jobId) || $jobId === '') {
            return;
        }

        $job = $this->repository->find($jobId);

        if ($job === null) {
            return;
        }

        $status = is_string($job['status'] ?? null) ? $job['status'] : '';
        if ($status === 'processing' || $status === 'complete') {
            return;
        }

        $attachments = isset($job['attachments']) && is_array($job['attachments'])
            ? $job['attachments']
            : [];

        if ($attachments === []) {
            $job['status'] = 'error';
            $job['error'] = __('Recognition job is missing attachment data.', 'context-alt-text');
            $this->repository->save($job);

            return;
        }

        $job['status'] = 'processing';
        $job['startedAt'] = time();
        $job['completedAt'] = null;
        $job['result'] = null;
        $job['error'] = null;
        $this->repository->save($job);

        try {
            $payload = [
                'images' => array_map(function (array $item): array {
                    $payloadImage = [
                        'filename' => sanitize_text_field((string) ($item['filename'] ?? '')),
                        'image_url' => $item['imageUrl'] ?? $item['image_url'] ?? null,
                    ];

                    $attachmentId = isset($item['id']) && is_numeric($item['id'])
                        ? (int) $item['id']
                        : null;

                    if ($attachmentId && function_exists('get_attached_file')) {
                        $file = get_attached_file($attachmentId);

                        if (is_string($file) && $file !== '' && file_exists($file)) {
                            $contents = file_get_contents($file);

                            if (is_string($contents) && $contents !== '') {
                                $payloadImage['image_base64'] = base64_encode($contents);
                            }
                        }
                    }

                    return $payloadImage;
                }, $attachments),
                'use_roster' => true,
            ];

            $response = $this->client->analyzeScene($payload);

            $job['status'] = 'complete';
            $job['result'] = $response;
            $job['completedAt'] = time();
            $job['observations'] = $this->persistObservations($job, $attachments, $response);
            $this->repository->save($job);
        } catch (RecognitionClientException $exception) {
            $job['status'] = 'error';
            $job['error'] = $exception->getMessage();
            $job['completedAt'] = null;
            $this->repository->save($job);
            $this->logFailure($job, $exception);

            if (isset($job['attachments']) && is_array($job['attachments'])) {
                foreach ($job['attachments'] as $attachment) {
                    if (is_array($attachment) && isset($attachment['id'])) {
                        $this->clearRetryLogEntry((int) $attachment['id']);
                    }
                }
            }
        }
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
     * @param array<int,array{id:int,image_url:string,filename:string}> $accepted
     * @return array{0:array<int,array{id:int,imageUrl:string,filename:string}>,1:array<int>}
     */
    private function filterEligibleAttachments(array $accepted): array
    {
        $log = $this->loadRetryLog();
        $now = time();
        $eligible = [];
        $deferred = [];

        foreach ($accepted as $item) {
            $attachmentId = (int) $item['id'];
            if ($attachmentId <= 0) {
                continue;
            }

            $lastAttempt = $log[$attachmentId] ?? 0;
            $cooldownRemaining = $lastAttempt !== 0 && ($now - $lastAttempt) < self::RETRY_COOLDOWN_SECONDS;

            if ($cooldownRemaining || count($eligible) >= self::MAX_BATCH_SIZE) {
                $deferred[] = $attachmentId;
                continue;
            }

            $eligible[] = [
                'id' => $attachmentId,
                'imageUrl' => $item['image_url'],
                'filename' => $item['filename'],
            ];

            $log[$attachmentId] = $now;
        }

        $this->saveRetryLog($log);

        return [$eligible, $deferred];
    }

    private function dispatchJob(string $jobId): void
    {
        if (function_exists('wp_schedule_single_event') && !(\defined('DISABLE_WP_CRON') && \constant('DISABLE_WP_CRON'))) {
            $timestamp = time() + self::JOB_RETRY_DELAY;

            if (!function_exists('wp_next_scheduled') || !wp_next_scheduled(self::PROCESS_HOOK, [$jobId])) {
                wp_schedule_single_event($timestamp, self::PROCESS_HOOK, [$jobId]);
            }
        }

        // Always process immediately so the admin UI receives a definitive status, even when cron is disabled.
        $this->processJob($jobId);
    }

    /**
     * @return array<int,int>
     */
    private function loadRetryLog(): array
    {
        if (function_exists('get_option')) {
            $log = get_option(self::RETRY_LOG_OPTION, []);
            if (is_array($log)) {
                return array_map(static fn($value): int => (int) $value, $log);
            }
        }

        return $this->retryLogFallback;
    }

    /**
     * @param array<int,int> $log
     */
    private function saveRetryLog(array $log): void
    {
        if (function_exists('update_option')) {
            update_option(self::RETRY_LOG_OPTION, $log);
        } else {
            $this->retryLogFallback = $log;
        }
    }

    private function clearRetryLogEntry(int $attachmentId): void
    {
        $log = $this->loadRetryLog();
        if (isset($log[$attachmentId])) {
            unset($log[$attachmentId]);
            $this->saveRetryLog($log);
        }
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
     * @param array<int,array{id:int,imageUrl?:string,image_url?:string,filename:string}> $accepted
     * @param array<string,mixed> $response
     */
    /**
     * @param array<string,mixed> $job
     * @param array<int,array{id:int,imageUrl?:string,image_url?:string,filename:string}> $accepted
     * @param array<string,mixed> $response
     * @return array<int,array<string,mixed>>
     */
    private function persistObservations(array $job, array $accepted, array $response): array
    {
        if (!isset($response['results']) || !is_array($response['results'])) {
            return [];
        }

        $results = array_values($response['results']);
        $attachments = [];

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
            $confidenceScore = $this->calculateConfidenceScore($observations);
            $sourceRemoteId = $this->resolveSourceRemoteId($observations);

            $payload = [
                'jobId' => $job['id'] ?? null,
                'attachmentId' => $attachmentId,
                'updatedAt' => $job['completedAt'] ?? time(),
                'observations' => $observations,
                'summary' => $summary,
                'context' => [
                    'filename' => $attachment['filename'] ?? '',
                    'imageUrl' => $attachment['imageUrl'] ?? $attachment['image_url'] ?? '',
                ],
                'confidenceScore' => $confidenceScore,
                'sourceRemoteId' => $sourceRemoteId,
            ];

            $this->observations->store($attachmentId, $payload);

            do_action(
                'cat_recognition_observations_stored',
                $job['id'] ?? null,
                $attachmentId,
                $payload
            );

            if ($observations !== []) {
                $this->autoResolveRosterMatches($attachmentId, $observations);
            }

            $attachments[] = $this->observations->get($attachmentId);
        }

        return $attachments;
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
            $candidates = $this->extractCandidates($entity['face_data']['candidates'] ?? []);

            $autoMatch = false;

            if ($roster !== null) {
                $threshold = $match['threshold'] > 0.0 ? $match['threshold'] : 0.6;

                if ($match['isMatch']) {
                    $autoMatch = true;
                } elseif ($match['similarity'] >= $threshold && $match['similarity'] > 0.0) {
                    $autoMatch = true;
                } else {
                    foreach ($candidates as $candidate) {
                        $candidateRemoteId = $candidate['remoteId'] ?? null;

                        if (
                            $candidateRemoteId !== null
                            && $candidateRemoteId === ($roster['remoteId'] ?? null)
                            && (
                                !empty($candidate['meetsThreshold'])
                                || $this->normalizeFloat($candidate['similarity'] ?? 0.0) >= $threshold
                            )
                        ) {
                            $autoMatch = true;

                            $candidateSimilarity = $this->normalizeFloat($candidate['similarity'] ?? 0.0);
                            if ($match['similarity'] <= 0.0 && $candidateSimilarity > 0.0) {
                                $match['similarity'] = $candidateSimilarity;
                            }

                            $candidateConfidence = $this->normalizeFloat($candidate['confidence'] ?? 0.0);
                            if ($match['confidence'] <= 0.0 && $candidateConfidence > 0.0) {
                                $match['confidence'] = $candidateConfidence;
                            }

                            break;
                        }
                    }
                }
            }

            if ($autoMatch) {
                $match['isMatch'] = true;
            }

            $status = $autoMatch && $roster !== null ? 'matched' : 'needs_review';

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
                'candidates' => $candidates,
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
                'confidence' => $this->normalizeFloat($candidate['confidence'] ?? ($candidate['similarity'] ?? 0.0)),
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

    /**
     * @param array<int,array<string,mixed>> $observations
     */
    private function calculateConfidenceScore(array $observations): float
    {
        $score = 0.0;

        foreach ($observations as $observation) {
            if (!is_array($observation)) {
                continue;
            }

            $score = max(
                $score,
                $this->normalizeFloat($observation['confidence'] ?? 0.0),
                isset($observation['match']['confidence'])
                    ? $this->normalizeFloat($observation['match']['confidence'])
                    : 0.0
            );
        }

        return $score;
    }

    /**
     * @param array<int,array<string,mixed>> $observations
     */
    private function resolveSourceRemoteId(array $observations): ?string
    {
        foreach ($observations as $observation) {
            if (!is_array($observation)) {
                continue;
            }

            if (isset($observation['roster']['remoteId']) && is_scalar($observation['roster']['remoteId'])) {
                return sanitize_text_field((string) $observation['roster']['remoteId']);
            }

            if (isset($observation['match']['remoteId']) && is_scalar($observation['match']['remoteId'])) {
                return sanitize_text_field((string) $observation['match']['remoteId']);
            }
        }

        return null;
    }

    /**
     * @param array<int,array<string,mixed>> $observations
     */
    private function autoResolveRosterMatches(int $attachmentId, array $observations): void
    {
        if ($this->rosterObservationManager === null) {
            return;
        }

        foreach ($observations as $observation) {
            if (!is_array($observation)) {
                continue;
            }

            if (($observation['status'] ?? '') !== 'matched') {
                continue;
            }

            $observationId = isset($observation['observationId']) && is_scalar($observation['observationId'])
                ? (string) $observation['observationId']
                : '';

            if ($observationId === '') {
                continue;
            }

            $roster = isset($observation['roster']) && is_array($observation['roster'])
                ? $observation['roster']
                : null;

            if ($roster === null || !isset($roster['remoteId'])) {
                continue;
            }

            $entry = [
                'remoteId' => $roster['remoteId'],
                'label' => $roster['displayName'] ?? $roster['name'] ?? ($observation['label'] ?? null),
                'name' => $roster['name'] ?? ($observation['label'] ?? null),
                'type' => $roster['type'] ?? ($observation['entityType'] ?? null),
            ];

            $resolution = [
                'attachmentId' => $attachmentId,
                'observationId' => $observationId,
                'status' => 'matched',
                'label' => $observation['label'] ?? null,
                'entityType' => $observation['entityType'] ?? null,
            ];

            $this->rosterObservationManager->resolveObservationWithRoster($resolution, $entry);
        }
    }
}
