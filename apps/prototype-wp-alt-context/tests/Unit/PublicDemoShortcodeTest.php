<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

require_once __DIR__ . '/../../src/public/class-public-demo-shortcode.php';

use AltContext\PublicSite\PublicDemoShortcode;
use AltContext\Tests\TestCase;

final class PublicDemoShortcodeTest extends TestCase
{
    public function testRegistersExpectedShortcode(): void
    {
        $shortcode = new PublicDemoShortcode();
        $shortcode->init();

        self::assertArrayHasKey('acx_demo_describe', $GLOBALS['__ac_shortcodes']);
        self::assertIsCallable($GLOBALS['__ac_shortcodes']['acx_demo_describe']);
    }

    public function testDisabledDemoRendersUnavailableWithoutEnqueuingClient(): void
    {
        $html = (new PublicDemoShortcode())->render();

        self::assertStringContainsString('not available right now', $html);
        self::assertSame([], $GLOBALS['__ac_scripts']);
        self::assertSame([], $GLOBALS['__ac_styles']);
    }

    public function testEnabledDemoRendersOnlyConfiguredAttachmentChoicesAndNonce(): void
    {
        $this->setOption('acx_public_demo_enabled', true);
        $this->setOption('acx_public_demo_media_ids', [41, 42]);
        $GLOBALS['__ac_attachment_urls'][41] = 'https://example.test/uploads/lake.jpg';
        $GLOBALS['__ac_attachment_titles'][41] = 'Lake';

        $html = (new PublicDemoShortcode())->render();

        self::assertStringContainsString('value="41"', $html);
        self::assertStringNotContainsString('value="42"', $html, 'Missing attachments must not become choices.');
        self::assertStringContainsString('data-nonce="nonce-wp_rest"', $html);
        self::assertStringContainsString('/wp-json/acx/v1/public/demo/describe', $html);
        self::assertSame('module', $GLOBALS['__ac_scripts']['acx-public-demo-describe']['data']['type']);
        self::assertArrayHasKey('acx-public-demo-describe', $GLOBALS['__ac_styles']);
    }

    public function testMultipleInstancesUseDistinctRadioGroupsAndLabelIds(): void
    {
        $this->setOption('acx_public_demo_enabled', true);
        $this->setOption('acx_public_demo_media_ids', [41]);
        $GLOBALS['__ac_attachment_urls'][41] = 'https://example.test/uploads/lake.jpg';

        $first = (new PublicDemoShortcode())->render();
        $second = (new PublicDemoShortcode())->render();
        preg_match('/<label[^>]+for="([^"]+)"[^>]*>.*?<input[^>]+id="([^"]+)"[^>]+name="([^"]+)"/s', $first, $firstMatch);
        preg_match('/<label[^>]+for="([^"]+)"[^>]*>.*?<input[^>]+id="([^"]+)"[^>]+name="([^"]+)"/s', $second, $secondMatch);

        self::assertCount(4, $firstMatch);
        self::assertCount(4, $secondMatch);
        self::assertNotSame($firstMatch[3], $secondMatch[3]);
        self::assertNotSame($firstMatch[2], $secondMatch[2]);
        self::assertSame($firstMatch[1], $firstMatch[2]);
        self::assertSame($secondMatch[1], $secondMatch[2]);
    }
}
