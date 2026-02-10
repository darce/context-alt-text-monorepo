<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Admin\Admin;
use AltContext\Tests\TestCase;
use ReflectionClass;

/**
 * Tests for Admin class.
 *
 * @covers \AltContext\Admin\Admin
 */
class AdminTest extends TestCase
{
    private Admin $admin;

    protected function setUp(): void
    {
        parent::setUp();
        $_GET = [];
        $this->admin = new Admin();
    }

    /**
     * Test get_tier returns valid tier from option.
     */
    public function testGetTierReturnsValidTierFromOption(): void
    {
        $this->setOption('acx_tier', 'pro');

        $tier = $this->invokePrivateMethod($this->admin, 'get_tier');

        $this->assertSame('pro', $tier);
    }

    /**
     * Test get_tier returns free as default.
     */
    public function testGetTierReturnsFreAsDefault(): void
    {
        // No tier option set
        $tier = $this->invokePrivateMethod($this->admin, 'get_tier');

        $this->assertSame('free', $tier);
    }

    /**
     * Test get_tier falls back to free for invalid tier.
     */
    public function testGetTierFallsBackToFreeForInvalidTier(): void
    {
        $this->setOption('acx_tier', 'invalid_tier_name');

        $tier = $this->invokePrivateMethod($this->admin, 'get_tier');

        $this->assertSame('free', $tier);
    }

    /**
     * Test get_tier with all valid tiers.
     *
     * @dataProvider validTierProvider
     */
    public function testGetTierWithValidTiers(string $tierName): void
    {
        $this->setOption('acx_tier', $tierName);

        $tier = $this->invokePrivateMethod($this->admin, 'get_tier');

        $this->assertSame($tierName, $tier);
    }

    /**
     * @return array<array{string}>
     */
    public static function validTierProvider(): array
    {
        return [
            ['free'],
            ['pro'],
            ['business'],
            ['enterprise'],
        ];
    }

    /**
     * Test get_tier sanitizes input.
     */
    public function testGetTierSanitizesInput(): void
    {
        // sanitize_key lowercases and removes special chars
        $this->setOption('acx_tier', 'PRO');

        $tier = $this->invokePrivateMethod($this->admin, 'get_tier');

        $this->assertSame('pro', $tier);
    }

    /**
     * Test localized SPA config includes canonical admin URLs.
     */
    public function testLocalizeSpaConfigIncludesAdminUrls(): void
    {
        $this->invokePrivateMethod($this->admin, 'localize_spa_config', ['test-handle']);

        $localized = $GLOBALS['__ac_localized_scripts']['test-handle']['AltContextAdmin'] ?? null;

        $this->assertIsArray($localized);
        $this->assertSame('/wp-admin/post.php', $localized['adminUrls']['mediaEditBase'] ?? null);
        $this->assertSame(
            '/wp-admin/admin.php?page=alt-context-roster&tab=clusters',
            $localized['adminUrls']['rosterClusters'] ?? null
        );
    }

    /**
     * Test enqueue_scripts enqueues and localizes build assets in production.
     */
    public function testEnqueueScriptsBuildAssetsInProduction(): void
    {
        unset($_ENV['WP_ENVIRONMENT_TYPE']);

        $this->admin->enqueue_scripts('toplevel_page_alt-context-dashboard');

        $this->assertArrayHasKey('alt-context-admin', $GLOBALS['__ac_scripts']);
        $this->assertArrayHasKey('alt-context-admin', $GLOBALS['__ac_localized_scripts']);
        $this->assertArrayNotHasKey('admin_notices', $GLOBALS['__ac_actions']);
    }

    /**
     * Test enqueue_scripts reports missing manifest and skips localization.
     */
    public function testEnqueueScriptsReportsMissingManifest(): void
    {
        unset($_ENV['WP_ENVIRONMENT_TYPE']);

        $admin = new Admin('/tmp/acx-missing-manifest.json');
        $admin->enqueue_scripts('toplevel_page_alt-context-dashboard');

        $this->assertArrayNotHasKey('alt-context-admin', $GLOBALS['__ac_scripts']);
        $this->assertArrayNotHasKey('alt-context-admin', $GLOBALS['__ac_localized_scripts']);
        $this->assertArrayHasKey('admin_notices', $GLOBALS['__ac_actions']);

        $noticeCallbacks = $GLOBALS['__ac_actions']['admin_notices'][10] ?? [];
        $this->assertNotEmpty($noticeCallbacks);

        ob_start();
        foreach ($noticeCallbacks as $callback) {
            ($callback['callback'])();
        }
        $output = (string) ob_get_clean();

        $this->assertStringContainsString('Alt Context admin assets could not be loaded.', $output);
    }

    public function testRenderRecognitionConfigNoticeAppearsOnPluginScreensWithFallback(): void
    {
        $_GET['page'] = 'alt-context-dashboard';

        ob_start();
        $this->admin->render_recognition_config_notice();
        $output = (string) ob_get_clean();

        $this->assertStringContainsString('Alt Context is using the local recognition URL fallback', $output);
    }

    public function testRenderRecognitionConfigNoticeDoesNotAppearWhenUrlConfigured(): void
    {
        $_GET['page'] = 'alt-context-dashboard';
        $this->setOption('acx_recognition_url', 'https://recognition.example');

        ob_start();
        $this->admin->render_recognition_config_notice();
        $output = (string) ob_get_clean();

        $this->assertSame('', $output);
    }

    public function testRenderRecognitionConfigNoticeIsScopedToPluginScreens(): void
    {
        $_GET['page'] = 'plugins';

        ob_start();
        $this->admin->render_recognition_config_notice();
        $output = (string) ob_get_clean();

        $this->assertSame('', $output);
    }

    /**
     * Helper to invoke private/protected methods.
     */
    private function invokePrivateMethod(object $object, string $methodName, array $args = []): mixed
    {
        $reflection = new ReflectionClass($object);
        $method = $reflection->getMethod($methodName);
        return $method->invokeArgs($object, $args);
    }
}
