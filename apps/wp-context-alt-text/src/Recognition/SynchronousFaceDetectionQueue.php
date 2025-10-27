<?php

declare(strict_types=1);

namespace ContextAltText\Recognition;

use ContextAltText\Domain\Clustering\ClusteringEngine;
use ContextAltText\Jobs\FaceDetectionJob;

/**
 * Executes detection jobs immediately. Useful while Action Scheduler integration is pending.
 */
class SynchronousFaceDetectionQueue implements FaceDetectionQueue
{
    private FaceDetectionJob $job;
    private ClusteringEngine $clusteringEngine;

    public function __construct(FaceDetectionJob $job, ClusteringEngine $clusteringEngine)
    {
        $this->job = $job;
        $this->clusteringEngine = $clusteringEngine;
    }

    public function enqueueBatch(array $attachmentIds, string $priority = 'normal'): array
    {
        foreach ($attachmentIds as $attachmentId) {
            $this->job->execute($attachmentId);
        }

        // Trigger clustering after all faces are detected and saved
        error_log('[SynchronousFaceDetectionQueue] Batch complete, triggering clustering');
        $this->clusteringEngine->clusterUnknownFaces();
        error_log('[SynchronousFaceDetectionQueue] Clustering complete');

        return [
            'job_id' => 'sync-' . uniqid('', true),
            'queued_count' => count($attachmentIds),
        ];
    }
}
