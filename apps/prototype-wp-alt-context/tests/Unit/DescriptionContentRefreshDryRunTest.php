<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Api\Services\DescriptionContentRefreshService;
use AltContext\Tests\TestCase;

/**
 * @covers \AltContext\Api\Services\DescriptionContentRefreshService
 */
class DescriptionContentRefreshDryRunTest extends TestCase
{
    public function testDryRunIdentifiesBlockAndClassicImageCandidates(): void
    {
        $this->setPostMeta(42, '_wp_attachment_image_alt', 'New bridge alt text');
        $GLOBALS['__ac_get_posts_results'] = [
            (object) [
                'ID' => 101,
                'post_type' => 'post',
                'post_title' => 'Block post',
                'post_content' => '<!-- wp:image {"id":42,"alt":"Old bridge alt"} --><figure><img class="wp-image-42" src="/bridge.jpg" alt="Old bridge alt" /></figure><!-- /wp:image -->',
            ],
            (object) [
                'ID' => 102,
                'post_type' => 'page',
                'post_title' => 'Classic page',
                'post_content' => '<p><img src="/bridge.jpg" alt="Legacy bridge alt" class="alignnone wp-image-42" /></p>',
            ],
        ];

        $result = (new DescriptionContentRefreshService())->dry_run([42], 10);

        $this->assertSame(2, $result['summary']['candidates']);
        $this->assertSame(0, $result['summary']['skipped']);
        $this->assertSame(
            [
                [
                    'post_id' => 101,
                    'post_type' => 'post',
                    'post_title' => 'Block post',
                    'media_id' => 42,
                    'existing_alt_text' => 'Old bridge alt',
                    'current_alt_text' => 'New bridge alt text',
                ],
                [
                    'post_id' => 102,
                    'post_type' => 'page',
                    'post_title' => 'Classic page',
                    'media_id' => 42,
                    'existing_alt_text' => 'Legacy bridge alt',
                    'current_alt_text' => 'New bridge alt text',
                ],
            ],
            $result['candidates']
        );
    }

    public function testDryRunSkipsAmbiguousMultipleReferences(): void
    {
        $this->setPostMeta(42, '_wp_attachment_image_alt', 'New bridge alt text');
        $GLOBALS['__ac_get_posts_results'] = [
            (object) [
                'ID' => 201,
                'post_type' => 'post',
                'post_title' => 'Gallery post',
                'post_content' => '<img class="wp-image-42" src="/one.jpg" alt="One old alt" /><img class="wp-image-42" src="/two.jpg" alt="Two old alt" />',
            ],
        ];

        $result = (new DescriptionContentRefreshService())->dry_run([42], 10);

        $this->assertSame(0, $result['summary']['candidates']);
        $this->assertSame(1, $result['summary']['skipped']);
        $this->assertSame('ambiguous_multiple_references', $result['skipped'][0]['reason']);
        $this->assertSame(201, $result['skipped'][0]['post_id']);
        $this->assertSame(42, $result['skipped'][0]['media_id']);
    }
}
