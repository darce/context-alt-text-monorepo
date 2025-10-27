<?php

declare(strict_types=1);

namespace ContextAltText\Recognition;

/**
 * Enqueue batches of attachments for face detection.
 */
interface FaceDetectionQueue
{
    /**
     * @param int[] $attachmentIds
     * @return array{job_id:string, queued_count:int}
     */
    public function enqueueBatch(array $attachmentIds, string $priority = 'normal'): array;
}
