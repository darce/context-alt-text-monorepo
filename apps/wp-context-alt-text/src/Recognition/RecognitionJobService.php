<?php

declare(strict_types=1);

namespace ContextAltText\Recognition;

use function __;
use function apply_filters;
use function array_filter;
use function array_map;
use function array_unique;
use function array_values;
use function basename;
use function current_user_can;
use function do_action;
use function get_post;
use function get_post_mime_type;
use function is_array;
use function is_scalar;
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

    public function __construct(RecognitionClient $client, RecognitionJobRepository $repository)
    {
        $this->client = $client;
        $this->repository = $repository;
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
        return $this->repository->find($jobId);
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
}
