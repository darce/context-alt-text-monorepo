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
    /**
     * SECAUDIT-1: a hostile decoded alt must not terminate the wp:image block
     * comment. The <img> alt leg is delegated to esc_attr, which the harness
     * stubs as identity, so the durability read-back (changed/failed) is not
     * asserted here; see the round-trip test below for the end-to-end path.
     */
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

        $this->assertSame(1, $result['summary']['candidates']);
        $this->assertCount(1, $GLOBALS['__ac_updated_posts']);
        $content = $GLOBALS['__ac_posts'][101]->post_content;
        // Lazy capture stops at the first " -->": if the alt closed the comment
        // early, the JSON would be truncated and fail to decode.
        $this->assertSame(1, preg_match('/^<!-- wp:image (.*?) -->/s', $content, $matches));
        $json = $matches[1];
        foreach (['--', '<', '>', '&', '\\"'] as $unsafe) {
            $this->assertStringNotContainsString($unsafe, $json);
        }
        $this->assertSame(['id' => 42, 'alt' => $expectedAlt], json_decode($json, true, 512, JSON_THROW_ON_ERROR));
        $this->assertStringContainsString('café', $json);
        $this->assertStringContainsString(' alt="' . esc_attr($expectedAlt) . '"', $content);
        $this->assertSame(1, substr_count($content, '<!-- wp:image '));
        $this->assertSame(1, substr_count($content, '<!-- /wp:image -->'));
    }

    /**
     * The \u escapes must survive wp_update_post's unslash so the stored block
     * JSON still decodes to the alt and the durability check passes.
     */
    public function testApplyPersistsEscapedBlockJsonThatRoundTrips(): void
    {
        $this->setPostMeta(42, '_wp_attachment_image_alt', 'x &lt;!-- y -- z &amp; café');
        $post = (object) [
            'ID' => 102,
            'post_type' => 'post',
            'post_title' => 'Block comment round-trip',
            'post_content' => '<!-- wp:image {"id":42,"alt":"Old alt"} --><figure><img class="wp-image-42" src="/image.jpg" alt="Old alt" /></figure><!-- /wp:image -->',
        ];
        $GLOBALS['__ac_posts'][102] = $post;
        $GLOBALS['__ac_get_posts_results'] = [$post];

        $result = (new DescriptionContentRefreshService())->apply([42], 10);

        $this->assertSame(1, $result['summary']['changed']);
        $this->assertSame(0, $result['summary']['failed']);
        $content = $GLOBALS['__ac_posts'][102]->post_content;
        $this->assertSame(1, preg_match('/^<!-- wp:image (.*?) -->/s', $content, $matches));
        $json = $matches[1];
        $this->assertStringContainsString('x \\u003c!\\u002d\\u002d y \\u002d\\u002d z \\u0026 café', $json);
        $this->assertSame(['id' => 42, 'alt' => 'x <!-- y -- z & café'], json_decode($json, true, 512, JSON_THROW_ON_ERROR));
    }
}
