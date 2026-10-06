<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

require_once __DIR__ . '/../../src/public/class-public-demo-shortcode.php';

use AltContext\PublicSite\PublicDemoShortcode;
use AltContext\Support\ViteManifest;
use AltContext\Tests\TestCase;
use ReflectionClass;

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

    public function testDemoStylesheetDependsOnCompiledTokenStylesheetWhenManifestEntryExists(): void
    {
        $this->setOption('acx_public_demo_enabled', true);
        $this->setOption('acx_public_demo_media_ids', [41]);
        $GLOBALS['__ac_attachment_urls'][41] = 'https://example.test/uploads/lake.jpg';

        $manifestPath = $this->writeManifest([
            'js/public/demo-tokens.scss' => [
                'file' => 'assets/public-demo-tokens-a1b2c3.css',
                'src' => 'js/public/demo-tokens.scss',
                'isEntry' => true,
            ],
        ]);
        $manifest = new ViteManifest(
            $manifestPath,
            static fn(string $relative): string => 'https://example.test/assets/' . ltrim($relative, '/')
        );

        try {
            $html = (new PublicDemoShortcode(
                static fn(string $entry): ?array => $manifest->entry_assets($entry)
            ))->render();

            self::assertStringContainsString('data-acx-demo', $html);
            self::assertSame(
                'https://example.test/assets/assets/public-demo-tokens-a1b2c3.css',
                $GLOBALS['__ac_styles']['acx-public-demo-tokens']['src'] ?? null
            );
            self::assertContains(
                'acx-public-demo-tokens',
                $GLOBALS['__ac_styles']['acx-public-demo-describe']['deps'] ?? []
            );
        } finally {
            unlink($manifestPath);
        }
    }

    public function testDefaultTokenResolverUsesManifestEntryAndEnqueuesCss(): void
    {
        $this->setOption('acx_public_demo_enabled', true);
        $this->setOption('acx_public_demo_media_ids', [41]);
        $GLOBALS['__ac_attachment_urls'][41] = 'https://example.test/uploads/lake.jpg';

        $manifestPath = $this->writeManifest([
            'js/public/demo-tokens.scss' => [
                'file' => 'assets/public-demo-tokens-default.css',
                'src' => 'js/public/demo-tokens.scss',
                'isEntry' => true,
            ],
        ]);
        $manifest = new ViteManifest(
            $manifestPath,
            static fn(string $relative): string => 'https://example.test/assets/' . ltrim($relative, '/')
        );

        try {
            $entryPoint = (new ReflectionClass(PublicDemoShortcode::class))
                ->getReflectionConstant('TOKEN_ENTRY_POINT');
            self::assertNotFalse($entryPoint);
            self::assertSame('js/public/demo-tokens.scss', $entryPoint->getValue());

            // The resolver is deliberately omitted; only its manifest dependency uses the fixture seam.
            $html = (new PublicDemoShortcode(null, $manifest))->render();

            self::assertStringContainsString('data-acx-demo', $html);
            self::assertSame(
                'https://example.test/assets/assets/public-demo-tokens-default.css',
                $GLOBALS['__ac_styles']['acx-public-demo-tokens']['src'] ?? null
            );
            self::assertContains(
                'acx-public-demo-tokens',
                $GLOBALS['__ac_styles']['acx-public-demo-describe']['deps'] ?? []
            );
        } finally {
            unlink($manifestPath);
        }
    }

    public function testDemoStillRendersWhenTokenManifestEntryIsMissing(): void
    {
        $this->setOption('acx_public_demo_enabled', true);
        $this->setOption('acx_public_demo_media_ids', [41]);
        $GLOBALS['__ac_attachment_urls'][41] = 'https://example.test/uploads/lake.jpg';

        $manifestPath = $this->writeManifest([]);
        $manifest = new ViteManifest(
            $manifestPath,
            static fn(string $relative): string => 'https://example.test/assets/' . ltrim($relative, '/')
        );

        try {
            $html = (new PublicDemoShortcode(
                static fn(string $entry): ?array => $manifest->entry_assets($entry)
            ))->render();

            self::assertStringContainsString('data-acx-demo', $html);
            self::assertArrayHasKey('acx-public-demo-describe', $GLOBALS['__ac_styles']);
            self::assertArrayNotHasKey('acx-public-demo-tokens', $GLOBALS['__ac_styles']);
            self::assertSame([], $GLOBALS['__ac_styles']['acx-public-demo-describe']['deps']);
        } finally {
            unlink($manifestPath);
        }
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

    public function testEnabledAvailableDemoRendersIllustrativeOutcomePreviewBeforeSubmit(): void
    {
        $this->setOption('acx_public_demo_enabled', true);
        $this->setOption('acx_public_demo_media_ids', [41]);
        $GLOBALS['__ac_attachment_urls'][41] = 'https://example.test/uploads/lake.jpg';
        $GLOBALS['__ac_attachment_titles'][41] = 'Lake';

        $html = (new PublicDemoShortcode())->render();

        self::assertStringContainsString('data-acx-demo-preview', $html);
        self::assertStringContainsString('Illustrative example — not a live result', $html);
        self::assertStringContainsString(
            'This example is not a description of your selected image. Your live result may differ.',
            $html
        );
        self::assertStringContainsString('Alex stands beside a bicycle outside a cafe.', $html);
        self::assertDoesNotMatchRegularExpression('/data-acx-demo-preview[^>]*\brole="(?:status|live)"/', $html);
        $previewPos = strpos($html, 'data-acx-demo-preview');
        $submitPos = strpos($html, 'class="acx-demo__submit"');
        self::assertNotFalse($previewPos);
        self::assertNotFalse($submitPos);
        self::assertLessThan($submitPos, $previewPos, 'Illustrative outcome must precede expensive submit.');
        self::assertMatchesRegularExpression('/data-acx-demo-result[^>]*\bhidden\b/', $html);
        self::assertMatchesRegularExpression('/<div class="acx-demo__result" data-acx-demo-result tabindex="-1" hidden><\/div>/', $html);
        self::assertStringNotContainsString('data-acx-demo-preview="data-acx-demo-result"', $html);
    }

    public function testDisabledDemoDoesNotRenderIllustrativeExampleOrSubmit(): void
    {
        $html = (new PublicDemoShortcode())->render();

        self::assertStringContainsString('not available right now', $html);
        self::assertStringNotContainsString('data-acx-demo-preview', $html);
        self::assertStringNotContainsString('Alex stands beside a bicycle outside a cafe.', $html);
        self::assertStringNotContainsString('acx-demo__submit', $html);
        self::assertStringNotContainsString('data-acx-demo', $html);
    }

    public function testEmptyAllowlistDoesNotRenderIllustrativeExampleOrSubmit(): void
    {
        $this->setOption('acx_public_demo_enabled', true);
        $this->setOption('acx_public_demo_media_ids', [99]);

        $html = (new PublicDemoShortcode())->render();

        self::assertStringContainsString('No demo images are available right now', $html);
        self::assertStringNotContainsString('data-acx-demo-preview', $html);
        self::assertStringNotContainsString('Alex stands beside a bicycle outside a cafe.', $html);
        self::assertStringNotContainsString('acx-demo__submit', $html);
    }

    /** @param array<string, mixed> $entries */
    private function writeManifest(array $entries): string
    {
        $path = tempnam(sys_get_temp_dir(), 'acx-demo-manifest-');
        if (false === $path) {
            self::fail('Unable to create a temporary Vite manifest.');
        }

        if (false === file_put_contents($path, json_encode($entries, JSON_THROW_ON_ERROR))) {
            unlink($path);
            self::fail('Unable to write a temporary Vite manifest.');
        }

        return $path;
    }
}
