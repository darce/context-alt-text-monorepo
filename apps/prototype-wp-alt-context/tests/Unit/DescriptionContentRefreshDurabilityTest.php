<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Api\Services\DescriptionContentRefreshService;
use AltContext\Tests\TestCase;

/**
 * R16-BR-13: wp_update_post returning a post ID is not proof post_content persisted.
 *
 * @covers \AltContext\Api\Services\DescriptionContentRefreshService
 */
class DescriptionContentRefreshDurabilityTest extends TestCase
{
    /**
     * Write is accepted (returns post ID) but storage filters the intended alt
     * out — service must report failed / post_content_not_persisted, not changed.
     */
    public function testApplyReportsFailedWhenStoredContentLacksIntendedAlt(): void
    {
        $this->setPostMeta(42, '_wp_attachment_image_alt', 'New bridge alt text');
        $originalContent = '<!-- wp:image {"id":42,"alt":"Old bridge alt"} --><figure><img class="wp-image-42" src="/bridge.jpg" alt="Old bridge alt" /></figure><!-- /wp:image -->';
        // Object-level filter emulates wp_insert_post_data / kses: property write
        // succeeds, but stored post_content is altered before consumers read it.
        $post = new ContentRefreshKsesFilteringPost(
            701,
            'post',
            'Filtered post',
            $originalContent
        );
        $GLOBALS['__ac_posts'][701] = $post;
        $GLOBALS['__ac_get_posts_results'] = [$post];

        $result = (new DescriptionContentRefreshService())->apply([42], 10);

        $this->assertSame(0, $result['summary']['changed']);
        $this->assertSame(1, $result['summary']['candidates']);
        $this->assertSame(1, $result['summary']['failed']);
        $this->assertSame([], $result['changed']);
        $this->assertCount(1, $result['failed']);
        $this->assertSame(701, $result['failed'][0]['post_id']);
        $this->assertSame(42, $result['failed'][0]['media_id']);
        $this->assertSame('post_content_not_persisted', $result['failed'][0]['reason']);
        // Write was accepted (not post_update_failed path).
        $this->assertCount(1, $GLOBALS['__ac_updated_posts']);
        // Img carrying the intended alt was stripped by the filter; block JSON
        // may still mention the string — consumer path is the img tag.
        $stored = (string) $GLOBALS['__ac_posts'][701]->post_content;
        $this->assertDoesNotMatchRegularExpression(
            '/<img\b[^>]*\bwp-image-42\b[^>]*>/i',
            $stored
        );
        $this->assertStringNotContainsString('alt="New bridge alt text"', $stored);
    }

    /**
     * Multi-media post: filter drops only one media's img. That entry fails;
     * the sibling that survived is still changed (per-entry verification).
     */
    public function testApplyVerifiesPerMediaWhenOneReplacementIsFiltered(): void
    {
        $this->setPostMeta(42, '_wp_attachment_image_alt', 'Alt for forty-two');
        $this->setPostMeta(43, '_wp_attachment_image_alt', 'Alt for forty-three');
        $originalContent =
            '<p><img class="wp-image-42" src="/a.jpg" alt="old 42" />' .
            '<img class="wp-image-43" src="/b.jpg" alt="old 43" /></p>';
        // Strip only wp-image-42 tags on write — emulates a selective filter.
        $post = new ContentRefreshSelectiveImgFilterPost(
            702,
            'post',
            'Partial filter post',
            $originalContent,
            42
        );
        $GLOBALS['__ac_posts'][702] = $post;
        $GLOBALS['__ac_get_posts_results'] = [$post];

        $result = (new DescriptionContentRefreshService())->apply([42, 43], 10);

        $this->assertSame(2, $result['summary']['candidates']);
        $this->assertSame(1, $result['summary']['changed']);
        $this->assertSame(1, $result['summary']['failed']);
        $this->assertSame(43, $result['changed'][0]['media_id']);
        $this->assertSame(42, $result['failed'][0]['media_id']);
        $this->assertSame('post_content_not_persisted', $result['failed'][0]['reason']);
        $this->assertStringContainsString('Alt for forty-three', (string) $GLOBALS['__ac_posts'][702]->post_content);
        $this->assertStringNotContainsString('Alt for forty-two', (string) $GLOBALS['__ac_posts'][702]->post_content);
    }
}

/**
 * Round-trips through wp_update_post's property assignment but strips every
 * &lt;img&gt; before storage — faithful enough stand-in for kses removing the
 * markup the refresh was meant to update. The stub's wp_update_post still
 * returns the post ID (write "succeeded").
 */
final class ContentRefreshKsesFilteringPost
{
    public int $ID;

    public string $post_type;

    public string $post_title;

    private string $stored_content;

    public function __construct(int $id, string $post_type, string $post_title, string $content)
    {
        $this->ID             = $id;
        $this->post_type      = $post_type;
        $this->post_title     = $post_title;
        $this->stored_content = $content;
    }

    public function __isset(string $name): bool
    {
        return 'post_content' === $name || isset($this->{$name});
    }

    public function __get(string $name): mixed
    {
        if ('post_content' === $name) {
            return $this->stored_content;
        }

        return null;
    }

    public function __set(string $name, mixed $value): void
    {
        if ('post_content' === $name) {
            $stripped = preg_replace('/<img\b[^>]*>/i', '', (string) $value);
            $this->stored_content = is_string($stripped) ? $stripped : '';

            return;
        }

        $this->{$name} = $value;
    }
}

/**
 * On post_content write, drops img tags for one media class only.
 */
final class ContentRefreshSelectiveImgFilterPost
{
    public int $ID;

    public string $post_type;

    public string $post_title;

    private string $stored_content;

    private int $strip_media_id;

    public function __construct(
        int $id,
        string $post_type,
        string $post_title,
        string $content,
        int $strip_media_id
    ) {
        $this->ID             = $id;
        $this->post_type      = $post_type;
        $this->post_title     = $post_title;
        $this->stored_content = $content;
        $this->strip_media_id = $strip_media_id;
    }

    public function __isset(string $name): bool
    {
        return 'post_content' === $name || isset($this->{$name});
    }

    public function __get(string $name): mixed
    {
        if ('post_content' === $name) {
            return $this->stored_content;
        }

        return null;
    }

    public function __set(string $name, mixed $value): void
    {
        if ('post_content' === $name) {
            $pattern = sprintf('/<img\b[^>]*\bwp-image-%d\b[^>]*>/i', $this->strip_media_id);
            $stripped = preg_replace($pattern, '', (string) $value);
            $this->stored_content = is_string($stripped) ? $stripped : (string) $value;

            return;
        }

        $this->{$name} = $value;
    }
}
