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

    /**
     * BR-141: entity-encoded meta (e.g. bare `<` stored as `&lt;`) must not
     * cause apply to rewrite the same post on every run.
     */
    public function testApplyIsIdempotentWhenMetaIsEntityEncoded(): void
    {
        // Storage form after sanitize_text_field("x <= y").
        $this->setPostMeta(42, '_wp_attachment_image_alt', 'x &lt;= y');
        $originalContent = '<p><img class="wp-image-42" src="/cmp.jpg" alt="old comparison" /></p>';
        $post            = (object) [
            'ID' => 401,
            'post_type' => 'post',
            'post_title' => 'Entity-encoded alt post',
            'post_content' => $originalContent,
        ];
        $GLOBALS['__ac_posts'][401] = $post;
        $GLOBALS['__ac_get_posts_results'] = [$post];

        $service = new DescriptionContentRefreshService();
        $apply   = $service->apply([42], 10);

        $this->assertSame(1, $apply['summary']['changed']);
        $this->assertNotSame($originalContent, $GLOBALS['__ac_posts'][401]->post_content);
        $this->assertStringNotContainsString('old comparison', $GLOBALS['__ac_posts'][401]->post_content);
        // Operator-facing payload is decoded (SPA does not decode entities).
        $this->assertSame('x <= y', $apply['changed'][0]['current_alt_text']);

        // Second pass: content already matches decoded meta → already_current.
        $dryRun = $service->dry_run([42], 10);

        $this->assertSame(0, $dryRun['summary']['candidates']);
        $this->assertSame(1, $dryRun['summary']['skipped']);
        $this->assertSame('already_current', $dryRun['skipped'][0]['reason']);
        $this->assertSame(401, $dryRun['skipped'][0]['post_id']);
    }

    /**
     * BR-141: block comment JSON holds a JSON string, not HTML — decoded text.
     */
    public function testApplyWritesDecodedAltIntoBlockJsonNotEntityEncoded(): void
    {
        $this->setPostMeta(42, '_wp_attachment_image_alt', 'x &lt;= y');
        $post = (object) [
            'ID' => 501,
            'post_type' => 'post',
            'post_title' => 'Block JSON entity alt',
            'post_content' => '<!-- wp:image {"id":42,"alt":"old alt"} --><figure><img class="wp-image-42" src="/cmp.jpg" alt="old alt" /></figure><!-- /wp:image -->',
        ];
        $GLOBALS['__ac_posts'][501] = $post;
        $GLOBALS['__ac_get_posts_results'] = [$post];

        (new DescriptionContentRefreshService())->apply([42], 10);

        $content = $GLOBALS['__ac_posts'][501]->post_content;
        $this->assertMatchesRegularExpression(
            '/<!--\s+wp:image\s+(\{.*?\})\s+-->/s',
            $content
        );
        preg_match('/<!--\s+wp:image\s+(\{.*?\})\s+-->/s', $content, $matches);
        $attributes = json_decode($matches[1], true);
        $this->assertIsArray($attributes);
        $this->assertSame('x <= y', $attributes['alt']);
        $this->assertStringNotContainsString('"alt":"x &lt;= y"', $content);
    }

    /**
     * BR-08: when wp_update_post fails, summary.changed is 0 and media is not in
     * changed[]. candidates still counts the intended write; failed is honest.
     */
    public function testApplyDoesNotCountChangedWhenPostUpdateFails(): void
    {
        $this->setPostMeta(42, '_wp_attachment_image_alt', 'New bridge alt text');
        $originalContent = '<!-- wp:image {"id":42,"alt":"Old bridge alt"} --><figure><img class="wp-image-42" src="/bridge.jpg" alt="Old bridge alt" /></figure><!-- /wp:image -->';
        $post = (object) [
            'ID' => 601,
            'post_type' => 'post',
            'post_title' => 'Unwritable post',
            'post_content' => $originalContent,
        ];
        $GLOBALS['__ac_posts'][601] = $post;
        $GLOBALS['__ac_get_posts_results'] = [$post];
        $GLOBALS['__ac_wp_update_post_fail'][601] = true;

        $result = (new DescriptionContentRefreshService())->apply([42], 10);

        $this->assertSame(0, $result['summary']['changed']);
        $this->assertSame(1, $result['summary']['candidates']);
        $this->assertSame(1, $result['summary']['failed']);
        $this->assertSame([], $result['changed']);
        $this->assertCount(1, $result['failed']);
        $this->assertSame(601, $result['failed'][0]['post_id']);
        $this->assertSame(42, $result['failed'][0]['media_id']);
        $this->assertSame('post_update_failed', $result['failed'][0]['reason']);
        // Content not mutated in storage.
        $this->assertSame($originalContent, $GLOBALS['__ac_posts'][601]->post_content);
        $this->assertCount(0, $GLOBALS['__ac_updated_posts']);
    }
}
