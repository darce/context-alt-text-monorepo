<?php

declare(strict_types=1);

namespace ContextAltText\Recognition;

use ContextAltText\Security\Security;
use WP_Error;
use WP_REST_Request;
use WP_REST_Response;
use function rest_ensure_response;

final class ScanController
{
    private const MAX_BATCH = 50;

    private Security $security;
    private FaceDetectionQueue $queue;

    public function __construct(Security $security, FaceDetectionQueue $queue)
    {
        $this->security = $security;
        $this->queue = $queue;
    }

    /**
     * @return WP_REST_Response|WP_Error
     */
    public function scanBatch(WP_REST_Request $request)
    {
        if (!$this->security->verifyCapability('upload_files')) {
            return new WP_Error('rest_forbidden', __('You do not have permission to scan media.', 'context-alt-text'), [
                'status' => 403,
            ]);
        }

        $attachmentIds = $request->get_param('attachment_ids');
        $priority = $request->get_param('priority') ?? 'normal';

        if (!is_array($attachmentIds) || $attachmentIds === []) {
            return new WP_Error('invalid_request', __('Provide one or more attachment IDs.', 'context-alt-text'), [
                'status' => 400,
            ]);
        }

        $normalizedIds = $this->normalizeAttachmentIds($attachmentIds);
        if ($normalizedIds === []) {
            return new WP_Error('invalid_request', __('No valid attachment IDs provided.', 'context-alt-text'), [
                'status' => 400,
            ]);
        }

        if (count($normalizedIds) > self::MAX_BATCH) {
            return new WP_Error('invalid_request', sprintf(
                __('You can scan at most %d attachments per request.', 'context-alt-text'),
                self::MAX_BATCH
            ), [
                'status' => 400,
            ]);
        }

        $normalizedPriority = $this->normalizePriority($priority);

        try {
            $result = $this->queue->enqueueBatch($normalizedIds, $normalizedPriority);
        } catch (\Throwable $exception) {
            return new WP_Error('scan_failed', sprintf(
                __('Face scan failed: %s', 'context-alt-text'),
                $exception->getMessage()
            ), [
                'status' => 500,
            ]);
        }

        return rest_ensure_response([
            'job_id' => $result['job_id'] ?? '',
            'queued_count' => $result['queued_count'] ?? count($normalizedIds),
            'priority' => $normalizedPriority,
        ]);
    }

    /**
     * @param array<int,mixed> $attachmentIds
     * @return int[]
     */
    private function normalizeAttachmentIds(array $attachmentIds): array
    {
        $normalized = [];
        foreach ($attachmentIds as $value) {
            $id = (int) $value;
            if ($id > 0) {
                $normalized[$id] = $id;
            }
        }

        return array_values($normalized);
    }

    private function normalizePriority($priority): string
    {
        if ($priority === 'high') {
            return 'high';
        }

        return 'normal';
    }
}
