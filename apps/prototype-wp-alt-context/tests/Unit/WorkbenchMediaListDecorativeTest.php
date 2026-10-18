<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Api\Api;
use AltContext\Tests\TestCase;
use WP_REST_Request;
use WP_REST_Response;

/**
 * HARM-BR-01: workbench media-list producer must honour acx_alt_decorative.
 *
 * DescriptionCandidateService already classifies empty-alt + marker as
 * decorative; the list producer must agree so marked items leave the missing
 * queue and report status complete (SPA union is not extended).
 *
 * Runtime stubs for WP_Query / attachment helpers are installed once in
 * setUpBeforeClass — tests/stubs/wp.php deliberately omits them, and this
 * lane cannot edit that shared file.
 *
 * @covers \AltContext\Api\Api::get_workbench_media
 */
class WorkbenchMediaListDecorativeTest extends TestCase
{
    private Api $api;

    public static function setUpBeforeClass(): void
    {
        parent::setUpBeforeClass();
        self::installWorkbenchMediaStubs();
    }

    protected function setUp(): void
    {
        parent::setUp();
        $this->api = new Api();
    }

    /**
     * Empty alt + acx_alt_decorative='1' must report status complete, not missing.
     * Matches DescriptionCandidateService::build_row precedence: decorative after
     * has_alt, before missing_alt — mapped to the SPA's complete bucket.
     */
    public function testEmptyAltWithDecorativeMarkerReportsStatusComplete(): void
    {
        $this->plantAttachment(100, 'Decorative spacer', '');
        $GLOBALS['__ac_post_meta'][100]['acx_alt_decorative'] = '1';
        // Control peer: same empty alt, no decorative marker.
        $this->plantAttachment(101, 'Genuinely missing', '');

        $request = new WP_REST_Request('GET', '/acx/v1/workbench/media');
        $request->set_param('page', 1);
        $request->set_param('per_page', 20);
        $request->set_param('status', 'all');
        $request->set_param('search', '');

        $response = $this->api->get_workbench_media($request);
        $this->assertInstanceOf(WP_REST_Response::class, $response);

        $data = $response->get_data();
        $this->assertIsArray($data);
        $this->assertArrayHasKey('items', $data);

        $byId = [];
        foreach ($data['items'] as $item) {
            $byId[(int) $item['id']] = $item;
        }

        $this->assertArrayHasKey(100, $byId, 'Decorative attachment must appear in unfiltered listing');
        $this->assertSame(
            'complete',
            $byId[100]['status'],
            'Empty alt + acx_alt_decorative=1 must map to complete (not missing)'
        );
        $this->assertNull(
            $byId[100]['altText'],
            'Empty alt must serialize as null, never "" (class-api.php:346)'
        );
        $this->assertTrue(
            $byId[100]['isDecorative'],
            'Empty alt + acx_alt_decorative=1 must emit isDecorative true on the wire'
        );
        // Control peer: empty alt without marker stays missing. Isolates $is_decorative
        // as the sole input difference between the two rows.
        $this->assertArrayHasKey(101, $byId, 'Control empty-alt peer must appear in unfiltered listing');
        $this->assertSame(
            ['complete', 'missing'],
            [$byId[100]['status'], $byId[101]['status']],
            'Decorative marker is the sole differentiator between complete and missing for empty alt'
        );
        $this->assertNull(
            $byId[101]['altText'],
            'Control empty alt also serializes as null (class-api.php:346)'
        );
        $this->assertFalse(
            $byId[101]['isDecorative'],
            'Empty alt without marker must emit isDecorative false'
        );
    }

    /**
     * Decorative attachment must leave the status=missing queue; a genuinely
     * missing peer (empty alt, no marker) must remain.
     */
    public function testDecorativeAttachmentExcludedFromMissingStatusListing(): void
    {
        $this->plantAttachment(200, 'Decorative spacer', '');
        $GLOBALS['__ac_post_meta'][200]['acx_alt_decorative'] = '1';

        $this->plantAttachment(201, 'Still missing', '');
        // Explicitly no decorative marker for 201.

        $request = new WP_REST_Request('GET', '/acx/v1/workbench/media');
        $request->set_param('page', 1);
        $request->set_param('per_page', 20);
        $request->set_param('status', 'missing');
        $request->set_param('search', '');

        $response = $this->api->get_workbench_media($request);
        $this->assertInstanceOf(WP_REST_Response::class, $response);

        $data = $response->get_data();
        $this->assertIsArray($data);
        $ids = array_map(
            static fn (array $item): int => (int) $item['id'],
            $data['items']
        );

        $this->assertNotContains(
            200,
            $ids,
            'Decorative attachment must not appear in status=missing listing'
        );
        $this->assertContains(
            201,
            $ids,
            'Empty alt without decorative marker must still appear in status=missing'
        );
        $this->assertSame(1, (int) $data['total']);
    }

    /**
     * Non-empty alt + leftover decorative marker: has_alt arm surfaces altText.
     * (Empty-alt + marker → complete is already pinned by
     * testEmptyAltWithDecorativeMarkerReportsStatusComplete; do not duplicate it.)
     */
    public function testCompleteBucketMapsHasAltArmWithLeftoverMarker(): void
    {
        // Non-empty alt + leftover decorative marker: has_alt arm surfaces altText.
        $this->plantAttachment(301, 'Described with stale flag', 'A real description.');
        $GLOBALS['__ac_post_meta'][301]['acx_alt_decorative'] = '1';

        $request = new WP_REST_Request('GET', '/acx/v1/workbench/media');
        $request->set_param('page', 1);
        $request->set_param('per_page', 20);
        $request->set_param('status', 'all');
        $request->set_param('search', '');

        $response = $this->api->get_workbench_media($request);
        $data = $response->get_data();
        $byId = [];
        foreach ($data['items'] as $item) {
            $byId[(int) $item['id']] = $item;
        }

        $this->assertSame('complete', $byId[301]['status']);
        $this->assertSame(
            'A real description.',
            $byId[301]['altText'],
            'Non-empty alt surfaces as altText even with leftover decorative marker'
        );
        $this->assertTrue(
            $byId[301]['isDecorative'],
            'Leftover decorative marker still emits isDecorative true when alt is non-empty'
        );
    }

    private function plantAttachment(int $id, string $title, string $altText): void
    {
        $GLOBALS['__ac_posts'][$id] = (object) [
            'ID'          => $id,
            'post_title'  => $title,
            'post_type'   => 'attachment',
            'post_status' => 'inherit',
        ];
        $GLOBALS['__ac_post_meta'][$id]['_wp_attachment_image_alt'] = $altText;
        $GLOBALS['__ac_attachment_mimes'][$id] = 'image/jpeg';
        $GLOBALS['__ac_attachment_urls'][$id] = "http://example.test/wp-content/uploads/{$id}.jpg";
    }

    /**
     * Install global WP_Query + attachment helpers once for this test class.
     * Meta-query-aware so dropping the decorative exclusion from the producer
     * meta_query makes testDecorativeAttachmentExcludedFromMissingStatusListing red.
     */
    private static function installWorkbenchMediaStubs(): void
    {
        if (!class_exists('WP_Query', false)) {
            // phpcs:ignore Squiz.PHP.Eval.Discouraged -- one-shot global test double; shared stubs omit WP_Query.
            eval(
                <<<'PHP'
class WP_Query
{
    /** @var list<int> */
    public $posts = [];

    /** @var int */
    public $found_posts = 0;

    /** @var int */
    public $max_num_pages = 1;

    /**
     * @param array<string,mixed> $query
     */
    public function __construct($query = [])
    {
        $ids = array_map('intval', array_keys($GLOBALS['__ac_posts'] ?? []));
        sort($ids);

        if (isset($query['meta_query']) && is_array($query['meta_query'])) {
            $ids = array_values(
                array_filter(
                    $ids,
                    static function ($id) use ($query) {
                        return WP_Query::matchesMetaQuery((int) $id, $query['meta_query']);
                    }
                )
            );
        }

        $perPage = isset($query['posts_per_page']) ? (int) $query['posts_per_page'] : count($ids);
        if ($perPage < 1) {
            $perPage = count($ids) > 0 ? count($ids) : 1;
        }

        $page = isset($query['paged']) ? max(1, (int) $query['paged']) : 1;
        $offset = ($page - 1) * $perPage;
        $pageIds = array_slice($ids, $offset, $perPage);

        $this->posts = $pageIds;
        $this->found_posts = count($ids);
        $this->max_num_pages = max(1, (int) ceil($this->found_posts / $perPage));
    }

    /**
     * @param array<string,mixed> $metaQuery
     */
    public static function matchesMetaQuery($id, $metaQuery)
    {
        $relation = strtoupper((string) ($metaQuery['relation'] ?? 'AND'));
        $results = [];

        foreach ($metaQuery as $key => $clause) {
            if ('relation' === $key || !is_array($clause)) {
                continue;
            }

            if (isset($clause['relation']) || !array_key_exists('key', $clause)) {
                $results[] = self::matchesMetaQuery($id, $clause);
                continue;
            }

            $results[] = self::matchesClause($id, $clause);
        }

        if ([] === $results) {
            return true;
        }

        if ('OR' === $relation) {
            return in_array(true, $results, true);
        }

        return !in_array(false, $results, true);
    }

    /**
     * @param array<string,mixed> $clause
     */
    public static function matchesClause($id, $clause)
    {
        $key = (string) ($clause['key'] ?? '');
        $compare = strtoupper((string) ($clause['compare'] ?? '='));
        $meta = $GLOBALS['__ac_post_meta'][$id] ?? [];
        $exists = array_key_exists($key, $meta);
        $stored = $exists ? $meta[$key] : null;

        if ('NOT EXISTS' === $compare) {
            return !$exists;
        }
        if ('EXISTS' === $compare) {
            return $exists;
        }
        if ('=' === $compare) {
            return $exists && (string) $stored === (string) ($clause['value'] ?? '');
        }
        if ('!=' === $compare) {
            return $exists && (string) $stored !== (string) ($clause['value'] ?? '');
        }

        return false;
    }
}
PHP
            );
        }

        if (!function_exists('get_the_title')) {
            // phpcs:ignore Squiz.PHP.Eval.Discouraged -- global helper omitted by shared stubs.
            eval(
                <<<'PHP'
function get_the_title($post = 0)
{
    $id = (int) $post;
    return isset($GLOBALS['__ac_posts'][$id]) && is_object($GLOBALS['__ac_posts'][$id])
        ? (string) ($GLOBALS['__ac_posts'][$id]->post_title ?? '')
        : '';
}
PHP
            );
        }

        if (!function_exists('wp_get_attachment_image_url')) {
            // phpcs:ignore Squiz.PHP.Eval.Discouraged -- global helper omitted by shared stubs.
            eval(
                <<<'PHP'
function wp_get_attachment_image_url($attachment_id, $size = 'thumbnail')
{
    return $GLOBALS['__ac_attachment_urls'][(int) $attachment_id] ?? false;
}
PHP
            );
        }

        if (!function_exists('wp_get_attachment_image_srcset')) {
            // phpcs:ignore Squiz.PHP.Eval.Discouraged -- global helper omitted by shared stubs.
            eval(
                <<<'PHP'
function wp_get_attachment_image_srcset($attachment_id, $size = 'medium')
{
    return false;
}
PHP
            );
        }

        if (!function_exists('wp_get_attachment_image_sizes')) {
            // phpcs:ignore Squiz.PHP.Eval.Discouraged -- global helper omitted by shared stubs.
            eval(
                <<<'PHP'
function wp_get_attachment_image_sizes($attachment_id, $size = 'medium')
{
    return false;
}
PHP
            );
        }

        if (!function_exists('get_edit_post_link')) {
            // phpcs:ignore Squiz.PHP.Eval.Discouraged -- global helper omitted by shared stubs.
            eval(
                <<<'PHP'
function get_edit_post_link($id = 0, $context = 'display')
{
    return sprintf('http://example.test/wp-admin/post.php?post=%d&action=edit', (int) $id);
}
PHP
            );
        }
    }
}
