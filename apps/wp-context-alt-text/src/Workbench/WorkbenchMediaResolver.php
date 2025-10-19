<?php

declare(strict_types=1);

namespace ContextAltText\Workbench;

use ContextAltText\Recognition\RecognitionObservationRepository;
use WP_Post;
use WP_Query;
use function class_exists;
use function admin_url;
use function function_exists;
use function get_post_mime_type;
use function get_post_meta;
use function get_post_modified_time;
use function is_array;
use function is_string;
use function max;
use function min;
use function is_scalar;
use function wp_get_attachment_image_url;
use function wp_get_attachment_metadata;

class WorkbenchMediaResolver
{
    private ?RecognitionObservationRepository $recognitionObservations;

    public function __construct(?RecognitionObservationRepository $recognitionObservations = null)
    {
        $this->recognitionObservations = $recognitionObservations;
    }

    /**
     * @param array<string,mixed> $args
     * @return array{items: array<int,array{id:string,title:string,status:string,thumbnailUrl:?string,updatedAt:?string,altText:?string,mimeType:?string,dimensions:array{width:int,height:int}|null,editUrl:?string,recognition?:array<string,mixed>|null}>, total:int, totalPages:int}
     */
    public function fetch(array $args = []): array
    {
        if (!function_exists('get_posts') || !class_exists(WP_Query::class)) {
            return [
                'items' => [],
                'total' => 0,
                'totalPages' => 0,
            ];
        }

        $page = max(1, (int) ($args['page'] ?? 1));
        $perPage = min(100, max(1, (int) ($args['per_page'] ?? 20)));
        $status = (string) ($args['status'] ?? 'missing');
        $search = $args['search'] ?? null;

        $queryArgs = $this->buildQueryArgs($page, $perPage, $status, $search);
        $wpQuery = $this->executeQuery($queryArgs);

        return $this->formatQueryResults($wpQuery);
    }

    /**
     * @return array<string,mixed>
     */
    private function buildQueryArgs(int $page, int $perPage, string $status, ?string $search): array
    {
        $queryArgs = [
            'post_type' => 'attachment',
            'post_status' => 'inherit',
            'post_mime_type' => 'image',
            'posts_per_page' => $perPage,
            'paged' => $page,
            'orderby' => 'modified',
            'order' => 'DESC',
        ];

        $metaQuery = $this->buildMetaQuery($status);
        if ($metaQuery !== null) {
            $queryArgs['meta_query'] = $metaQuery;
        }

        if (is_string($search) && $search !== '') {
            $queryArgs['s'] = $search;
        }

        return $queryArgs;
    }

    private function executeQuery(array $queryArgs): WP_Query
    {
        $wpQuery = new WP_Query();
        $wpQuery->query($queryArgs);
        return $wpQuery;
    }

    /**
     * @return array{items: array<int,array{id:string,title:string,status:string,thumbnailUrl:?string,updatedAt:?string,altText:?string,mimeType:?string,dimensions:array{width:int,height:int}|null,editUrl:?string,recognition?:array<string,mixed>|null}>, total:int, totalPages:int}
     */
    private function formatQueryResults(WP_Query $wpQuery): array
    {
        $total = (int) ($wpQuery->found_posts ?? 0);
        $totalPagesRaw = (int) ($wpQuery->max_num_pages ?? 0);
        $totalPages = $total > 0 ? max(1, $totalPagesRaw) : 0;

        return [
            'items' => $this->mapPosts($wpQuery->posts ?? []),
            'total' => $total,
            'totalPages' => $totalPages,
        ];
    }

    /**
     * @return list<array{id:string,title:string,status:string,thumbnailUrl:?string,updatedAt:?string,altText:?string,mimeType:?string,dimensions:array{width:int,height:int}|null,editUrl:?string}>
     */
    private function mapPosts(array $posts): array
    {
        if (!function_exists('get_post_meta')) {
            return [];
        }

        $items = [];

        foreach ($posts as $post) {
            if (!$post instanceof WP_Post) {
                continue;
            }

            $mapped = $this->mapPost($post);
            if ($mapped !== null) {
                $items[] = $mapped;
            }
        }

        return $items;
    }

    /**
     * @return array{id:string,title:string,status:string,thumbnailUrl:?string,updatedAt:?string,altText:?string,mimeType:?string,dimensions:array{width:int,height:int}|null,editUrl:?string,recognition?:array<string,mixed>|null}|null
     */
    private function mapPost(WP_Post $post): ?array
    {
        $id = (int) $post->ID;
        if ($id <= 0) {
            return null;
        }

        $alt = (string) get_post_meta($id, '_wp_attachment_image_alt', true);
        $status = $alt === '' ? 'missing' : 'published';

        $thumbnail = $this->getPreferredThumbnail($id);

        $updatedAt = function_exists('get_post_modified_time')
            ? get_post_modified_time('c', true, $post)
            : ($post->post_modified_gmt ?? null);

        $mimeType = function_exists('get_post_mime_type') ? get_post_mime_type($id) : null;

        $dimensions = null;
        if (function_exists('wp_get_attachment_metadata')) {
            $metadata = wp_get_attachment_metadata($id);
            if (is_array($metadata) && isset($metadata['width'], $metadata['height'])) {
                $dimensions = [
                    'width' => (int) $metadata['width'],
                    'height' => (int) $metadata['height'],
                ];
            }
        }

        $editUrl = function_exists('admin_url')
            ? admin_url('post.php?post=' . $id . '&action=edit')
            : null;

        return [
            'id' => (string) $id,
            'title' => (string) $post->post_title,
            'status' => $status,
            'thumbnailUrl' => $thumbnail ?: null,
            'updatedAt' => $updatedAt ?: null,
            'altText' => $alt !== '' ? $alt : null,
            'mimeType' => $mimeType ?: null,
            'dimensions' => $dimensions,
            'editUrl' => $editUrl,
            'recognition' => $this->buildRecognitionMetadata($id),
        ];
    }

    /**
     * @return array<string,mixed>|null
     */
    private function buildMetaQuery(string $status): ?array
    {
        if ($status === 'all') {
            return null;
        }

        // Currently only "missing" is supported; future statuses will expand here.
        return [
            'relation' => 'OR',
            [
                'key' => '_wp_attachment_image_alt',
                'compare' => 'NOT EXISTS',
            ],
            [
                'key' => '_wp_attachment_image_alt',
                'value' => '',
                'compare' => '=',
            ],
        ];
    }

    private function getPreferredThumbnail(int $attachmentId): ?string
    {
        if (!function_exists('wp_get_attachment_image_url')) {
            return null;
        }

        $preferredSizes = ['medium', 'thumbnail', 'medium_large', 'large', 'full'];

        if (function_exists('wp_get_attachment_metadata')) {
            $metadata = wp_get_attachment_metadata($attachmentId);
            if (is_array($metadata) && isset($metadata['sizes']) && is_array($metadata['sizes'])) {
                foreach ($preferredSizes as $size) {
                    if (isset($metadata['sizes'][$size])) {
                        $generated = wp_get_attachment_image_url($attachmentId, $size);
                        if (is_string($generated) && $generated !== '') {
                            return $generated;
                        }
                    }
                }
            }
        }

        foreach ($preferredSizes as $size) {
            $generated = wp_get_attachment_image_url($attachmentId, $size);
            if (is_string($generated) && $generated !== '') {
                return $generated;
            }
        }

        return null;
    }

    /**
     * @return array<string,mixed>|null
     */
    private function buildRecognitionMetadata(int $attachmentId): ?array
    {
        if ($this->recognitionObservations === null) {
            return null;
        }

        $record = $this->recognitionObservations->get($attachmentId);

        if (!is_array($record) || !isset($record['summary']) || !is_array($record['summary'])) {
            return null;
        }

        $summary = $record['summary'];
        $matchedCount = (int) ($summary['matched'] ?? 0);
        $needsReviewCount = (int) ($summary['needs_review'] ?? 0);

        $status = $this->determineRecognitionStatus($summary);
        $matchedRoster = $this->extractMatchedRoster($record['observations'] ?? []);

        if ($status === 'unknown' && $matchedRoster === null && $matchedCount === 0 && $needsReviewCount === 0) {
            return null;
        }

        return [
            'status' => $status,
            'matchedCount' => max(0, $matchedCount),
            'needsReviewCount' => max(0, $needsReviewCount),
            'matchedRoster' => $matchedRoster,
            'updatedAt' => isset($record['updatedAt']) && is_scalar($record['updatedAt'])
                ? (int) $record['updatedAt']
                : null,
        ];
    }

    /**
     * @param array<string,mixed> $summary
     */
    private function determineRecognitionStatus(array $summary): string
    {
        $needsReviewCount = (int) ($summary['needs_review'] ?? 0);
        $matchedCount = (int) ($summary['matched'] ?? 0);

        if ($needsReviewCount > 0) {
            return 'needs_review';
        }

        if ($matchedCount > 0) {
            return 'matched';
        }

        return 'unknown';
    }

    /**
     * @param array<mixed> $observations
     * @return array{remoteId:string|null,displayName:string|null,name:string|null}|null
     */
    private function extractMatchedRoster(array $observations): ?array
    {
        foreach ($observations as $observation) {
            if (!is_array($observation) || ($observation['status'] ?? '') !== 'matched') {
                continue;
            }

            if (!isset($observation['roster']) || !is_array($observation['roster'])) {
                continue;
            }

            $roster = $observation['roster'];

            return [
                'remoteId' => $this->extractScalarString($roster, 'remoteId'),
                'displayName' => $this->extractScalarString($roster, 'displayName', 'display_name'),
                'name' => $this->extractScalarString($roster, 'name'),
            ];
        }

        return null;
    }

    /**
     * @param array<string,mixed> $data
     */
    private function extractScalarString(array $data, string $key, ?string $fallbackKey = null): ?string
    {
        if (isset($data[$key]) && is_scalar($data[$key])) {
            return (string) $data[$key];
        }

        if ($fallbackKey !== null && isset($data[$fallbackKey]) && is_scalar($data[$fallbackKey])) {
            return (string) $data[$fallbackKey];
        }

        return null;
    }
}
