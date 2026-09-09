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
        // Post-order DFS: imported-chunk CSS first so the entry can override
        // shared rules when wp_enqueue_style emits in this order.
        $this->assertSame(
            [
                'https://cdn.test/assets/deep-def.css',
                'https://cdn.test/assets/shared-abc.css',
                'https://cdn.test/assets/guide-main.css',
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

    public function testManifestPathReturnsConstructorPath(): void
    {
        $path = $this->fixturePath('nested.json');
        $manifest = new ViteManifest($path, $this->urlBuilder());

        $this->assertSame($path, $manifest->manifest_path());
    }

    public function testFromPluginResolvesDefaultManifestPathAndUrlBuilder(): void
    {
        $manifest = ViteManifest::from_plugin();
        $this->assertInstanceOf(ViteManifest::class, $manifest);

        $primary = ACX_PLUGIN_DIR . 'public/assets/dist/.vite/manifest.json';
        $fallback = ACX_PLUGIN_DIR . 'public/assets/dist/manifest.json';
        $resolved = $manifest->manifest_path();
        $this->assertTrue(
            $resolved === $primary || $resolved === $fallback,
            'from_plugin() must use the .vite manifest when readable, else dist/manifest.json'
        );
        if (is_readable($primary)) {
            $this->assertSame($primary, $resolved);
        } else {
            $this->assertSame($fallback, $resolved);
        }

        $reflection = new ReflectionClass($manifest);
        $builderProperty = $reflection->getProperty('urlBuilder');
        $builderProperty->setAccessible(true);
        $builder = $builderProperty->getValue($manifest);
        $this->assertIsCallable($builder);
        $this->assertSame(
            plugins_url('public/assets/dist/assets/guide-main.js', 'alt-context/alt-context.php'),
            $builder('assets/guide-main.js')
        );
    }

    public function testAdminRequireOnceTargetDeclaresViteManifestWithoutAutoload(): void
    {
        $adminFile = realpath(__DIR__ . '/../../src/admin/class-admin.php');
        self::assertIsString($adminFile, 'class-admin.php must exist');

        $contents = (string) file_get_contents($adminFile);
        $this->assertStringContainsString(
            "require_once __DIR__ . '/../support/class-vite-manifest.php';",
            $contents,
            'class-admin.php must explicitly require class-vite-manifest.php ([rg-016])'
        );

        if (!preg_match(
            "/require_once\\s+__DIR__\\s*\\.\\s*'(\\/\\.\\.\\/support\\/class-vite-manifest\\.php)'\\s*;/",
            $contents,
            $match
        )) {
            self::fail('class-admin.php must require_once class-vite-manifest.php');
        }

        $target = realpath(dirname($adminFile) . $match[1]);
        self::assertIsString($target, 'class-admin.php require_once target must exist');

        $script = sprintf(
            'require %s; var_export(class_exists(%s, false));',
            var_export($target, true),
            var_export('AltContext\\Support\\ViteManifest', true)
        );
        $output = trim((string) shell_exec(sprintf('php -r %s 2>&1', escapeshellarg($script))));
        $this->assertSame(
            'true',
            $output,
            'class-admin.php require_once target must declare ViteManifest with autoload disabled; got: '
                . var_export($output, true)
        );
    }
}
