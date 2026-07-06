<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Api\Services\DescriptionContentRefreshService;
use AltContext\Tests\TestCase;

/**
 * @covers \AltContext\Api\Services\DescriptionContentRefreshService
 */
class DescriptionContentRefreshApplyTest extends TestCase
{
    public function testApplyUpdatesOnlyConfidentCandidateContent(): void
    {
        $this->setPostMeta(42, '_wp_attachment_image_alt', 'New bridge alt text');
        $post = (object) [
            'ID' => 101,
            'post_type' => 'post',
            'post_title' => 'Block post',
            'post_content' => '<!-- wp:image {"id":42,"alt":"Old bridge alt"} --><figure><img class="wp-image-42" src="/bridge.jpg" alt="Old bridge alt" /></figure><!-- /wp:image -->',
        ];
        $GLOBALS['__ac_posts'][101] = $post;
        $GLOBALS['__ac_get_posts_results'] = [$post];

        $result = (new DescriptionContentRefreshService())->apply([42], 10);

        $this->assertSame(false, $result['summary']['dry_run']);
        $this->assertSame(1, $result['summary']['changed']);
        $this->assertSame(101, $result['changed'][0]['post_id']);
        $this->assertStringContainsString('alt="New bridge alt text"', $GLOBALS['__ac_posts'][101]->post_content);
        $this->assertCount(1, $GLOBALS['__ac_updated_posts']);
    }

    public function testApplyDoesNotUpdateAmbiguousReferences(): void
    {
        $this->setPostMeta(42, '_wp_attachment_image_alt', 'New bridge alt text');
        $post = (object) [
            'ID' => 201,
            'post_type' => 'post',
            'post_title' => 'Gallery post',
            'post_content' => '<img class="wp-image-42" src="/one.jpg" alt="One old alt" /><img class="wp-image-42" src="/two.jpg" alt="Two old alt" />',
        ];
        $GLOBALS['__ac_posts'][201] = $post;
        $GLOBALS['__ac_get_posts_results'] = [$post];

        $result = (new DescriptionContentRefreshService())->apply([42], 10);

        $this->assertSame(0, $result['summary']['changed']);
        $this->assertSame(1, $result['summary']['skipped']);
        $this->assertSame('ambiguous_multiple_references', $result['skipped'][0]['reason']);
        $this->assertCount(0, $GLOBALS['__ac_updated_posts']);
    }

    public function testApplyUpdatesGutenbergBlockAltAttribute(): void
    {
        $this->setPostMeta(42, '_wp_attachment_image_alt', 'New bridge alt text');
        $post = (object) [
            'ID' => 301,
            'post_type' => 'post',
            'post_title' => 'Block post',
            'post_content' => '<!-- wp:image {"id":42,"alt":"Old bridge alt"} --><figure><img class="wp-image-42" src="/bridge.jpg" alt="Old bridge alt" /></figure><!-- /wp:image -->',
        ];
        $GLOBALS['__ac_posts'][301] = $post;
        $GLOBALS['__ac_get_posts_results'] = [$post];

        (new DescriptionContentRefreshService())->apply([42], 10);

        $this->assertStringContainsString('"alt":"New bridge alt text"', $GLOBALS['__ac_posts'][301]->post_content);
        $this->assertStringContainsString('alt="New bridge alt text"', $GLOBALS['__ac_posts'][301]->post_content);
    }
}
