<?php

declare(strict_types=1);

namespace ContextAltText\Recognition;

use function get_transient;
use function is_array;
use function set_transient;
use function time;
use function wp_generate_uuid4;

class RecognitionJobRepository
{
    private const TRANSIENT_PREFIX = 'context_alt_text_recognition_job_';
    private const TTL = 3600; // 1 hour

    /**
     * @param array<string,mixed> $data
     *
     * @return array<string,mixed>
     */
    public function create(array $data): array
    {
        $jobId = wp_generate_uuid4();

        $job = [
            'id' => $jobId,
            'status' => 'pending',
            'attachments' => $data['attachments'] ?? [],
            'rejected' => $data['rejected'] ?? [],
            'createdAt' => time(),
            'updatedAt' => time(),
            'startedAt' => null,
            'completedAt' => null,
            'result' => null,
            'error' => null,
            'observations' => [],
        ];

        $this->persist($job);

        return $job;
    }

    /**
     * @return array<string,mixed>|null
     */
    public function find(string $jobId): ?array
    {
        $job = get_transient($this->key($jobId));

        if (is_array($job)) {
            return $job;
        }

        return null;
    }

    /**
     * @param array<string,mixed> $job
     */
    public function save(array $job): void
    {
        $job['updatedAt'] = time();
        $this->persist($job);
    }

    /**
     * @param array<string,mixed> $job
     */
    private function persist(array $job): void
    {
        set_transient($this->key((string) $job['id']), $job, self::TTL);
    }

    private function key(string $jobId): string
    {
        return self::TRANSIENT_PREFIX . $jobId;
    }
}
