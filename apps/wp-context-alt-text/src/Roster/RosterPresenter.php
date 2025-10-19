<?php

declare(strict_types=1);

namespace ContextAltText\Roster;

use function array_filter;
use function array_values;
use function call_user_func;
use function count;
use function function_exists;
use function get_term_by;
use function human_time_diff;
use function in_array;
use function is_array;
use function is_numeric;
use function is_scalar;
use function is_string;
use function is_wp_error;
use function sanitize_text_field;
use function strtoupper;
use function time;
use function strtotime;

final class RosterPresenter
{
    /**
     * Count attachments tagged with this roster entity.
     *
     * @param string|null $remoteId
     * @return int
     */
    private static function getTaggedImageCount(?string $remoteId): int
    {
        if (!$remoteId) {
            return 0;
        }

        $termSlug = 'cat-recognition-' . $remoteId;
        $term = get_term_by('slug', $termSlug, RosterTaxonomy::TAXONOMY);

        if (!$term || is_wp_error($term)) {
            return 0;
        }

        return (int) $term->count;
    }

    /**
     * @param array<string,mixed>|mixed $entry
     * @return array<string,mixed>
     */
    public static function normalizeEntry($entry): array
    {
        if (!is_array($entry)) {
            return self::emptyEntry();
        }

        $metadata = isset($entry['metadata']) && is_array($entry['metadata']) ? $entry['metadata'] : [];

        $referenceImages = [];
        if (isset($entry['referenceImages']) && is_array($entry['referenceImages'])) {
            $referenceImages = array_values(
                array_filter(
                    $entry['referenceImages'],
                    static fn($candidate) => is_array($candidate)
                )
            );
        }

        $status = self::determineStatus($entry, $metadata);
        $avatarUrl = self::resolveAvatarUrl($metadata, $referenceImages);
        $avatarId = self::resolveAvatarId($metadata);

        $label = isset($entry['label']) && is_scalar($entry['label'])
            ? sanitize_text_field((string) $entry['label'])
            : '';

        $type = isset($entry['type']) && is_scalar($entry['type'])
            ? sanitize_text_field((string) $entry['type'])
            : '';

        $remoteId = isset($entry['remoteId']) ? (string) $entry['remoteId'] : null;

        return [
            'remoteId' => $remoteId,
            'label' => $label,
            'type' => $type,
            'status' => $status,
            'updatedAt' => isset($entry['updatedAt']) ? (string) $entry['updatedAt'] : null,
            'metadata' => $metadata,
            'referenceImages' => $referenceImages,
            'avatarUrl' => $avatarUrl,
            'avatarId' => $avatarId,
            'referenceImageCount' => self::getTaggedImageCount($remoteId),
        ];
    }

    /**
     * @param array<int,array<string,mixed>> $entries
     * @param array<string,mixed> $syncState
     * @return array<string,mixed>
     */
    public static function buildStats(array $entries, array $syncState = []): array
    {
        $countByStatus = static function (string $status) use ($entries): int {
            return count(
                array_filter(
                    $entries,
                    static fn($entry) => isset($entry['status']) && $entry['status'] === $status
                )
            );
        };

        $lastSyncAt = isset($syncState['lastSyncAt']) && is_string($syncState['lastSyncAt'])
            ? $syncState['lastSyncAt']
            : null;

        $lastSyncHuman = null;
        if ($lastSyncAt) {
            $timestamp = strtotime($lastSyncAt);
            if ($timestamp) {
                $lastSyncHuman = human_time_diff($timestamp, time());
            }
        }

        return [
            'total' => count($entries),
            'synced' => $countByStatus('SYNCED'),
            'local' => $countByStatus('LOCAL'),
            'conflicts' => $countByStatus('CONFLICT'),
            'lastSyncAt' => $lastSyncAt,
            'lastSyncHuman' => $lastSyncHuman,
            'metrics' => [
                'created' => (int) ($syncState['created'] ?? 0),
                'updated' => (int) ($syncState['updated'] ?? 0),
                'deleted' => (int) ($syncState['deleted'] ?? 0),
                'errors' => (int) ($syncState['errors'] ?? 0),
                'conflicts' => (int) ($syncState['conflicts'] ?? 0),
            ],
        ];
    }

    /**
     * @param array<string,mixed> $entry
     * @param array<string,mixed> $metadata
     */
    private static function determineStatus(array $entry, array $metadata): string
    {
        $candidates = [
            $metadata['syncStatus'] ?? null,
            $metadata['sync_status'] ?? null,
        ];

        foreach ($candidates as $candidate) {
            if (is_string($candidate)) {
                $normalized = strtoupper($candidate);
                if (in_array($normalized, ['LOCAL', 'SYNCED', 'CONFLICT'], true)) {
                    return $normalized;
                }
            }
        }

        if (
            !empty($metadata['conflict'])
            || !empty($metadata['conflictReason'])
            || (!empty($entry['conflict']) && $entry['conflict'])
        ) {
            return 'CONFLICT';
        }

        $remoteId = $entry['remoteId'] ?? null;
        if ($remoteId === null || $remoteId === '') {
            return 'LOCAL';
        }

        return 'SYNCED';
    }

    /**
     * @param array<string,mixed> $metadata
     * @param array<int,array<string,mixed>> $referenceImages
     */
    private static function resolveAvatarUrl(array $metadata, array $referenceImages): ?string
    {
        $candidates = [];

        foreach (['avatarUrl', 'avatar_url', 'avatar'] as $key) {
            if (isset($metadata[$key]) && is_string($metadata[$key]) && $metadata[$key] !== '') {
                $candidates[] = $metadata[$key];
            }
        }

        foreach ($referenceImages as $image) {
            if (!is_array($image)) {
                continue;
            }

            foreach (['thumbnail_url', 'thumbnailUrl', 'image_url', 'url'] as $key) {
                if (isset($image[$key]) && is_string($image[$key]) && $image[$key] !== '') {
                    $candidates[] = $image[$key];
                }
            }
        }

        foreach ($candidates as $candidate) {
            $value = (string) $candidate;
            if ($value === '') {
                continue;
            }

            $sanitized = $value;
            if (function_exists('esc_url_raw')) {
                $maybeSanitized = call_user_func('esc_url_raw', $value);
                if (is_string($maybeSanitized) && $maybeSanitized !== '') {
                    $sanitized = $maybeSanitized;
                }
            }

            if ($sanitized !== '') {
                return $sanitized;
            }
        }

        return null;
    }

    /**
     * @return array<string,mixed>
     */
    private static function emptyEntry(): array
    {
        return [
            'remoteId' => null,
            'label' => '',
            'type' => '',
            'status' => 'LOCAL',
            'updatedAt' => null,
            'metadata' => [],
            'referenceImages' => [],
            'avatarUrl' => null,
            'avatarId' => null,
            'referenceImageCount' => 0,
        ];
    }

    /**
     * @param array<string,mixed> $metadata
     */
    private static function resolveAvatarId(array $metadata): ?int
    {
        foreach (['avatarAttachmentId', 'avatar_attachment_id', 'avatarId', 'avatar_id'] as $key) {
            if (!isset($metadata[$key])) {
                continue;
            }

            $candidate = $metadata[$key];

            if (is_numeric($candidate)) {
                $value = (int) $candidate;

                if ($value > 0) {
                    return $value;
                }
            }
        }

        return null;
    }
}
