<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Api\Services\DescriptionContentRefreshService;
use AltContext\Tests\TestCase;

/**
 * @covers \AltContext\Api\Services\DescriptionContentRefreshService
 */
class DescriptionContentRefreshBlockCommentEscapeTest extends TestCase
{
    public function testApplyEscapesBlockCommentAndImageAttributeAfterDecodingMeta(): void
    {
        $storedAlt = '--><img src=x onerror=alert(1)><!-- &lt;script&gt; " café & tea';
        $expectedAlt = html_entity_decode($storedAlt, ENT_QUOTES);
        $this->setPostMeta(42, '_wp_attachment_image_alt', $storedAlt);
        $post = (object) [
            'ID' => 101,
            'post_type' => 'post',
            'post_title' => 'Block comment escaping',
            'post_content' => '<!-- wp:image {"id":42,"alt":"Old alt"} --><figure><img class="wp-image-42" src="/image.jpg" alt="Old alt" /></figure><!-- /wp:image -->',
        ];
        $GLOBALS['__ac_posts'][101] = $post;
        $GLOBALS['__ac_get_posts_results'] = [$post];

        $result = (new DescriptionContentRefreshService())->apply([42], 10);

        $this->assertSame(1, $result['summary']['changed']);
        $content = $GLOBALS['__ac_posts'][101]->post_content;
        $this->assertSame(1, preg_match('/^<!-- wp:image (.*?) -->/s', $content, $matches));
        $json = $matches[1];
        foreach (['--', '<', '>', '&', '\\"'] as $unsafe) {
            $this->assertStringNotContainsString($unsafe, $json);
        }
        $this->assertSame(['id' => 42, 'alt' => $expectedAlt], json_decode($json, true, 512, JSON_THROW_ON_ERROR));
        $this->assertStringContainsString('café', $json);
        $this->assertStringContainsString(' alt="' . esc_attr($expectedAlt) . '"', $content);
        $this->assertStringNotContainsString('<img src=x', $content);
        $this->assertStringNotContainsString('<script>', $content);
        $this->assertSame(1, substr_count($content, '<!-- wp:image '));
        $this->assertSame(1, substr_count($content, '<!-- /wp:image -->'));
    }
}
