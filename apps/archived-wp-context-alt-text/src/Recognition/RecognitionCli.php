<?php

declare(strict_types=1);

namespace ContextAltText\Recognition;

use WP_CLI;
use WP_CLI_Command;
use function array_map;
use function count;
use function implode;
use function is_array;
use function is_string;
use function sprintf;
use function wp_json_encode;

class RecognitionCli extends WP_CLI_Command
{
    private RecognitionClient $client;
    private RecognitionJobService $jobs;

    public function __construct(RecognitionClient $client, RecognitionJobService $jobs)
    {
        $this->client = $client;
        $this->jobs = $jobs;
    }

    /**
     * Run a health check against the recognition service.
     *
     * ## EXAMPLES
     *
     *     wp cat-recognition health
     */
    public function health(array $args, array $assocArgs): void
    {
        unset($args, $assocArgs);

        try {
            $response = $this->client->getHealth();
        } catch (RecognitionClientException $exception) {
            WP_CLI::error(sprintf('Recognition health check failed: %s', $exception->getMessage()));
            return;
        }

        $status = '';

        if (isset($response['status']) && is_string($response['status'])) {
            $status = $response['status'];
        }

        if ($status === '') {
            $status = 'ok';
        }

        WP_CLI::success(sprintf('Recognition service is reachable (status: %s).', $status));

        $payload = wp_json_encode($response);

        if (is_string($payload) && $payload !== '') {
            WP_CLI::log($payload);
        }
    }

    /**
     * Submit a recognition job for the provided attachment ID.
     *
     * ## OPTIONS
     *
     * <attachment_id>
     * : The attachment ID to analyze.
     *
     * ## EXAMPLES
     *
     *     wp cat-recognition analyze 123
     *
     * @param array<int,mixed> $args
     * @param array<string,mixed> $assocArgs
     */
    public function analyze(array $args, array $assocArgs): void
    {
        unset($assocArgs);

        $attachmentId = isset($args[0]) ? (int) $args[0] : 0;

        if ($attachmentId <= 0) {
            WP_CLI::error('Attachment ID must be a positive integer.');
            return;
        }

        $result = $this->jobs->submit([$attachmentId]);

        if (empty($result['job'])) {
            $message = isset($result['message']) && is_string($result['message'])
                ? $result['message']
                : 'No valid attachments were provided for recognition.';

            WP_CLI::error($message);
            return;
        }

        $jobId = (string) ($result['jobId'] ?? ($result['job']['id'] ?? 'unknown'));
        $status = isset($result['status']) && is_string($result['status']) ? $result['status'] : 'processing';

        WP_CLI::success(sprintf('Recognition job %s queued (status: %s).', $jobId, $status));

        $accepted = isset($result['accepted']) ? (int) $result['accepted'] : 0;
        $rejected = [];

        if (isset($result['rejected']) && is_array($result['rejected'])) {
            $rejected = $result['rejected'];
        }

        WP_CLI::log(sprintf('Accepted: %d', $accepted));
        WP_CLI::log(sprintf('Rejected: %d', count($rejected)));

        if (!empty($rejected)) {
            $ids = implode(', ', array_map(static fn($value): string => (string) $value, $rejected));
            WP_CLI::log(sprintf('Rejected attachment IDs: %s', $ids));
        }

        $job = $this->jobs->getJob($jobId);

        if ($job === null || !is_array($job)) {
            return;
        }

        $jobStatus = isset($job['status']) && is_string($job['status']) ? $job['status'] : 'unknown';
        WP_CLI::log(sprintf('Current job status: %s', $jobStatus));

        if (isset($job['error']) && is_string($job['error']) && $job['error'] !== '') {
            WP_CLI::warning(sprintf('Job error: %s', $job['error']));
        }
    }
}
