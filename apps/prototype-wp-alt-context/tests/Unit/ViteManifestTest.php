<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Support\ViteManifest;
use AltContext\Tests\TestCase;
use ReflectionClass;

/**
 * Nested Vite 5 manifest resolution: entry CSS plus recursive imported-chunk CSS.
 *
 * @covers \AltContext\Support\ViteManifest
 */
class ViteManifestTest extends TestCase
{
    private function fixturePath(string $name): string
    {
        return dirname(__DIR__) . '/fixtures/vite-manifest/' . $name;
    }

    /**
     * @return callable(string):string
     */
    private function urlBuilder(): callable
    {
        return static function (string $relative): string {
            return 'https://cdn.test/' . ltrim($relative, '/');
        };
    }

    private function nestedManifest(): ViteManifest
    {
        return new ViteManifest($this->fixturePath('nested.json'), $this->urlBuilder());
    }

    public function testEntryAssetsCollectsCssDepthFirstAndSkipsDynamicImports(): void
    {
        $assets = $this->nestedManifest()->entry_assets('js/guide/main.tsx');

        $this->assertIsArray($assets);
        $this->assertSame('https://cdn.test/assets/guide-main.js', $assets['js']);
        $this->assertSame(
            [
                'https://cdn.test/assets/guide-main.css',
                'https://cdn.test/assets/shared-abc.css',
                'https://cdn.test/assets/deep-def.css',
            ],
            $assets['css']
        );
        $this->assertNotContains('https://cdn.test/assets/lazy-xyz.css', $assets['css']);
    }

    public function testEntryAssetsReturnsNullForMissingEntry(): void
    {
        $this->assertNull($this->nestedManifest()->entry_assets('js/missing/main.tsx'));
    }

    public function testEntryAssetsReturnsNullForUnreadablePath(): void
    {
        $manifest = new ViteManifest(
            $this->fixturePath('does-not-exist.json'),
            $this->urlBuilder()
        );

        $this->assertNull($manifest->entry_assets('js/guide/main.tsx'));
    }

    public function testEntryAssetsReturnsNullForMalformedJson(): void
    {
        $manifest = new ViteManifest($this->fixturePath('malformed.json'), $this->urlBuilder());

        $this->assertNull($manifest->entry_assets('js/guide/main.tsx'));
    }

    public function testEntryAssetsReturnsNullWhenEntryLacksFile(): void
    {
        $manifest = new ViteManifest($this->fixturePath('missing-file.json'), $this->urlBuilder());

        $this->assertNull($manifest->entry_assets('js/guide/main.tsx'));
    }

    public function testFromPluginResolvesDefaultManifestPathAndUrlBuilder(): void
    {
        $manifest = ViteManifest::from_plugin();
        $this->assertInstanceOf(ViteManifest::class, $manifest);

        $reflection = new ReflectionClass($manifest);
        $pathProperty = $reflection->getProperty('manifestPath');
        $pathProperty->setAccessible(true);
        $builderProperty = $reflection->getProperty('urlBuilder');
        $builderProperty->setAccessible(true);

        $primary = ACX_PLUGIN_DIR . 'public/assets/dist/.vite/manifest.json';
        $fallback = ACX_PLUGIN_DIR . 'public/assets/dist/manifest.json';
        $resolved = $pathProperty->getValue($manifest);
        $this->assertTrue(
            $resolved === $primary || $resolved === $fallback,
            'from_plugin() must use the .vite manifest when readable, else dist/manifest.json'
        );
        if (is_readable($primary)) {
            $this->assertSame($primary, $resolved);
        } else {
            $this->assertSame($fallback, $resolved);
        }

        $builder = $builderProperty->getValue($manifest);
        $this->assertIsCallable($builder);
        $this->assertSame(
            plugins_url('public/assets/dist/assets/guide-main.js', 'alt-context/alt-context.php'),
            $builder('assets/guide-main.js')
        );
    }
}
