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

    private function buildManifestFixturePath(): string
    {
        return dirname(__DIR__) . '/fixtures/admin-manifest.json';
    }

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
            '/wp-admin/admin.php?page=alt-context-roster',
            $localized['adminUrls']['roster'] ?? null
        );
        $this->assertArrayNotHasKey('rosterClusters', $localized['adminUrls'] ?? []);
        $this->assertStringNotContainsString(
            'tab=clusters',
            (string) ($localized['adminUrls']['roster'] ?? '')
        );
    }

    /**
     * UXP-NET-2: SPA localize payload carries ajaxUrl + nonce for rest-nonce refresh.
     */
    public function testLocalizeSpaConfigIncludesAjaxUrlAndNonce(): void
    {
        $this->invokePrivateMethod($this->admin, 'localize_spa_config', ['test-handle']);

        $localized = $GLOBALS['__ac_localized_scripts']['test-handle']['AltContextAdmin'] ?? null;

        $this->assertIsArray($localized);
        $this->assertArrayHasKey('nonce', $localized);
        $this->assertSame('nonce-wp_rest', $localized['nonce'] ?? null);
        $this->assertArrayHasKey('ajaxUrl', $localized);
        $this->assertSame('/wp-admin/admin-ajax.php', $localized['ajaxUrl'] ?? null);
    }

    /**
     * UXP-NET-2: attachment-edit localize payload carries ajaxUrl + nonce.
     */
    public function testLocalizeAttachmentEditConfigIncludesAjaxUrlAndNonce(): void
    {
        $_GET['post'] = '55';
        $GLOBALS['__ac_posts'][55] = (object) [
            'ID' => 55,
            'post_type' => 'attachment',
        ];
        $GLOBALS['__ac_attachment_image_src'][55]['full'] = [
            'http://example.test/wp-content/uploads/face.jpg',
            1200,
            800,
        ];

        $this->invokePrivateMethod($this->admin, 'localize_attachment_edit_config', ['test-handle']);

        $localized = $GLOBALS['__ac_localized_scripts']['test-handle']['AltContextAttachmentEdit'] ?? null;

        $this->assertIsArray($localized);
        $this->assertArrayHasKey('nonce', $localized);
        $this->assertSame('nonce-wp_rest', $localized['nonce'] ?? null);
        $this->assertArrayHasKey('ajaxUrl', $localized);
        $this->assertSame('/wp-admin/admin-ajax.php', $localized['ajaxUrl'] ?? null);
    }

    public function testLocalizeSpaConfigIncludesRetentionEndpoints(): void
    {
        $this->invokePrivateMethod($this->admin, 'localize_spa_config', ['test-handle']);

        $localized = $GLOBALS['__ac_localized_scripts']['test-handle']['AltContextAdmin'] ?? null;

        $this->assertIsArray($localized);
        $this->assertSame('http://example.test/wp-json/acx/v1/retention/status', $localized['endpoints']['retentionStatus'] ?? null);
        $this->assertSame('http://example.test/wp-json/acx/v1/retention/policy', $localized['endpoints']['retentionPolicy'] ?? null);
        $this->assertSame('http://example.test/wp-json/acx/v1/retention/export', $localized['endpoints']['retentionExport'] ?? null);
        $this->assertSame('http://example.test/wp-json/acx/v1/retention/purge', $localized['endpoints']['retentionPurge'] ?? null);
    }

    public function testLocalizeSpaConfigIncludesDescribeEndpoint(): void
    {
        $this->invokePrivateMethod($this->admin, 'localize_spa_config', ['test-handle']);

        $localized = $GLOBALS['__ac_localized_scripts']['test-handle']['AltContextAdmin'] ?? null;

        $this->assertIsArray($localized);
        $this->assertSame(
            'http://example.test/wp-json/acx/v1/recognition/describe',
            $localized['endpoints']['recognitionDescribe'] ?? null
        );
        $this->assertSame(
            'http://example.test/wp-json/acx/v1/recognition/describe/candidates',
            $localized['endpoints']['recognitionDescribeCandidates'] ?? null
        );
        $this->assertSame(
            'http://example.test/wp-json/acx/v1/recognition/describe/history',
            $localized['endpoints']['recognitionDescribeHistory'] ?? null
        );
    }

    public function testLocalizeSpaConfigIncludesRecognitionSource(): void
    {
        // RECOG-1: local is a dev hatch via filter (option tier retired).
        $this->setOption('acx_recognition_url', 'https://recognition.example');
        add_filter('acx_recognition_source', static fn (): string => 'local');

        $this->invokePrivateMethod($this->admin, 'localize_spa_config', ['test-handle']);

        $localized = $GLOBALS['__ac_localized_scripts']['test-handle']['AltContextAdmin'] ?? null;

        $this->assertIsArray($localized);
        $this->assertSame('local', $localized['recognitionSource'] ?? null);
    }

    public function testLocalizeSpaConfigUsesCanonicalTenantIdentity(): void
    {
        $this->invokePrivateMethod($this->admin, 'localize_spa_config', ['test-handle']);

        $localized = $GLOBALS['__ac_localized_scripts']['test-handle']['AltContextAdmin'] ?? null;

        $this->assertIsArray($localized);
        $this->assertSame(self::currentTenantId(), $localized['tenant_id'] ?? null);
    }

    /**
     * Test enqueue_scripts enqueues and localizes build assets in production.
     */
    public function testEnqueueScriptsBuildAssetsInProduction(): void
    {
        unset($_ENV['WP_ENVIRONMENT_TYPE']);

        $admin = new Admin($this->buildManifestFixturePath());

        $admin->enqueue_scripts('toplevel_page_alt-context-dashboard');

        $this->assertArrayHasKey('alt-context-admin', $GLOBALS['__ac_scripts']);
        $this->assertArrayHasKey('alt-context-admin', $GLOBALS['__ac_localized_scripts']);
        $this->assertSame(
            'http://example.test/wp-content/plugins/alt-context/public/assets/dist/assets/admin-test.js',
            $GLOBALS['__ac_scripts']['alt-context-admin']['src'] ?? null
        );
        $this->assertSame(
            'http://example.test/wp-content/plugins/alt-context/public/assets/dist/assets/admin-test.css',
            $GLOBALS['__ac_styles']['alt-context-admin-0']['src'] ?? null
        );
        $this->assertArrayNotHasKey('admin_notices', $GLOBALS['__ac_actions']);
    }

    /**
     * @runInSeparateProcess
     * @preserveGlobalState disabled
     */
    public function testEnqueueScriptsUsesDevServerWhenViteIsReachable(): void
    {
        define('ACX_VITE_DEV_SERVER', 'http://localhost:5173');
        $_ENV['WP_ENVIRONMENT_TYPE'] = 'development';

        // Probe to Vite returns 200 — Vite is reachable.
        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => '',
        ]);

        $admin = new Admin();
        $admin->enqueue_scripts('toplevel_page_alt-context-dashboard');

        // Dev server path enqueues two scripts: -dev (vite client) and -entry (main.tsx).
        $this->assertArrayHasKey('alt-context-admin-dev', $GLOBALS['__ac_scripts']);
        $this->assertArrayHasKey('alt-context-admin-entry', $GLOBALS['__ac_scripts']);
        $this->assertStringContainsString(
            '@vite/client',
            $GLOBALS['__ac_scripts']['alt-context-admin-dev']['src']
        );

        // The probe was a HEAD request to the @vite/client URL.
        $calls = $this->getHttpCalls();
        $this->assertCount(1, $calls);
        $this->assertSame('HEAD', $calls[0]['method']);
        $this->assertStringContainsString('@vite/client', $calls[0]['url']);
    }

    /**
     * @runInSeparateProcess
     * @preserveGlobalState disabled
     */
    public function testEnqueueScriptsFallsBackToBuildBundleWhenViteIsUnreachable(): void
    {
        define('ACX_VITE_DEV_SERVER', 'http://localhost:5173');
        $_ENV['WP_ENVIRONMENT_TYPE'] = 'development';

        // Probe to Vite returns a WP_Error — connection refused / unreachable.
        $this->queueHttpResponse(new \WP_Error('http_request_failed', 'Connection refused'));

        // Use the real built manifest fixture path so build_assets path can resolve.
        $admin = new Admin($this->buildManifestFixturePath());
        $admin->enqueue_scripts('toplevel_page_alt-context-dashboard');

        // Dev script handles MUST NOT be enqueued — fallback to built bundle path.
        $this->assertArrayNotHasKey('alt-context-admin-dev', $GLOBALS['__ac_scripts']);
        $this->assertArrayNotHasKey('alt-context-admin-entry', $GLOBALS['__ac_scripts']);
        // Build bundle script handle should be enqueued instead.
        $this->assertArrayHasKey('alt-context-admin', $GLOBALS['__ac_scripts']);

        // The probe still happened (one HEAD request); no other HTTP calls were made.
        $calls = $this->getHttpCalls();
        $this->assertCount(1, $calls);
        $this->assertSame('HEAD', $calls[0]['method']);
    }

    /**
     * @runInSeparateProcess
     * @preserveGlobalState disabled
     */
    public function testEnqueueScriptsFallsBackToBuildBundleWhenViteReturns500(): void
    {
        define('ACX_VITE_DEV_SERVER', 'http://localhost:5173');
        $_ENV['WP_ENVIRONMENT_TYPE'] = 'development';

        // Probe returns 500 — Vite is reachable but unhealthy. Fall back.
        $this->queueHttpResponse([
            'response' => ['code' => 500, 'message' => 'Internal Server Error'],
            'body' => '',
        ]);

        $admin = new Admin($this->buildManifestFixturePath());
        $admin->enqueue_scripts('toplevel_page_alt-context-dashboard');

        $this->assertArrayNotHasKey('alt-context-admin-dev', $GLOBALS['__ac_scripts']);
        $this->assertArrayNotHasKey('alt-context-admin-entry', $GLOBALS['__ac_scripts']);
        $this->assertArrayHasKey('alt-context-admin', $GLOBALS['__ac_scripts']);
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

    public function testRenderRecognitionConfigNoticeAppearsWhenLocalModeIsActive(): void
    {
        // RECOG-1: local mode is now reached only via the ACX_RECOGNITION_SOURCE dev
        // hatch (filter here); the notice is a developer diagnostic with no Settings link.
        $_GET['page'] = 'alt-context-dashboard';
        $this->setOption('acx_recognition_url', 'https://recognition.example');
        add_filter('acx_recognition_source', static fn (): string => 'local');

        ob_start();
        $this->admin->render_recognition_config_notice();
        $output = (string) ob_get_clean();

        $this->assertStringContainsString('developer local-recognition hatch (ACX_RECOGNITION_SOURCE=local) and will send requests to http://localhost:8000', $output);
        $this->assertStringContainsString('Remove that constant to use the hosted recognition service.', $output);
        $this->assertStringNotContainsString('Go to Settings', $output);
    }

    public function testRenderRecognitionConfigNoticeDoesNotAppearWhenServiceModeIsConfigured(): void
    {
        $_GET['page'] = 'alt-context-dashboard';
        $this->setOption('acx_recognition_url', 'https://recognition.example');
        $this->setOption('acx_recognition_source', 'service');

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

    /**
     * Registers a post of the given type so get_post_type() resolves it.
     */
    private function registerPost(int $id, string $postType): void
    {
        $post = new \stdClass();
        $post->ID = $id;
        $post->post_type = $postType;
        $GLOBALS['__ac_posts'][$id] = $post;
    }

    /**
     * The guided prototype's live run needs one real attachment id, and the
     * only way it reaches the browser is this payload. An unset option must
     * publish null so the panel can say "not configured" rather than submit 0.
     *
     * The value is asserted as a string because wp_localize_script casts every
     * scalar on the way out; that string is the shape the browser parses.
     */
    public function testLocalizeSpaConfigPublishesTheGuidedLiveMediaId(): void
    {
        $this->registerPost(4211, 'attachment');
        $this->setOption('acx_guided_live_media_id', 4211);

        $this->invokePrivateMethod($this->admin, 'localize_spa_config', ['test-handle']);

        $localized = $GLOBALS['__ac_localized_scripts']['test-handle']['AltContextAdmin'] ?? null;

        $this->assertIsArray($localized);
        $this->assertSame('4211', $localized['guided_live_media_id']);
    }

    /**
     * @return array<string, array{0: mixed}>
     */
    public static function unstorableGuidedLiveMediaIdProvider(): array
    {
        return [
            // filter_var(true) is 1, so without the boolean rejection a boolean
            // option publishes attachment 1 -- whatever that happens to be.
            'boolean true' => [true],
            'boolean false' => [false],
            'array' => [[4211]],
            // A float is scalar and not boolean, so the old deny-list waved it
            // through to filter_var, which truncates it to a real id. The JS
            // mirror rejects the string '4211.0'; the two ends must agree.
            'float' => [4211.0],
            'float with a fraction' => [4211.7],
        ];
    }

    /**
     * @dataProvider unstorableGuidedLiveMediaIdProvider
     *
     * @param mixed $raw
     */
    public function testLocalizeSpaConfigRejectsOptionTypesThatAreNotAStringOrAnInt($raw): void
    {
        $this->registerPost(1, 'attachment');
        $this->registerPost(4211, 'attachment');
        $this->setOption('acx_guided_live_media_id', $raw);

        $this->invokePrivateMethod($this->admin, 'localize_spa_config', ['test-handle']);

        $localized = $GLOBALS['__ac_localized_scripts']['test-handle']['AltContextAdmin'] ?? null;

        $this->assertIsArray($localized);
        $this->assertNull($localized['guided_live_media_id']);
    }

    /**
     * @return array<string, array{0: string|false}>
     */
    public static function nonAttachmentGuidedLiveMediaIdProvider(): array
    {
        return [
            'plain post' => ['post'],
            'page' => ['page'],
            'missing post' => [false],
        ];
    }

    /**
     * A well-formed id is not a subject. Publishing one that is not an
     * attachment enables a live run that can only fail, in place of the
     * blocked line the panel has for exactly this misconfiguration.
     *
     * @dataProvider nonAttachmentGuidedLiveMediaIdProvider
     *
     * @param string|false $postType
     */
    public function testLocalizeSpaConfigRejectsAnIdThatIsNotAnAttachment($postType): void
    {
        if (false !== $postType) {
            $this->registerPost(4211, $postType);
        }
        $this->setOption('acx_guided_live_media_id', 4211);

        $this->invokePrivateMethod($this->admin, 'localize_spa_config', ['test-handle']);

        $localized = $GLOBALS['__ac_localized_scripts']['test-handle']['AltContextAdmin'] ?? null;

        $this->assertIsArray($localized);
        $this->assertNull($localized['guided_live_media_id']);
    }

    public function testLocalizeSpaConfigPublishesNullGuidedLiveMediaIdWhenUnset(): void
    {
        $this->invokePrivateMethod($this->admin, 'localize_spa_config', ['test-handle']);

        $localized = $GLOBALS['__ac_localized_scripts']['test-handle']['AltContextAdmin'] ?? null;

        $this->assertIsArray($localized);
        $this->assertArrayHasKey('guided_live_media_id', $localized);
        $this->assertNull($localized['guided_live_media_id']);
    }

    public function testLocalizeSpaConfigRejectsANonPositiveGuidedLiveMediaId(): void
    {
        $this->setOption('acx_guided_live_media_id', '-3');

        $this->invokePrivateMethod($this->admin, 'localize_spa_config', ['test-handle']);

        $localized = $GLOBALS['__ac_localized_scripts']['test-handle']['AltContextAdmin'] ?? null;

        $this->assertIsArray($localized);
        $this->assertArrayHasKey('guided_live_media_id', $localized);
        $this->assertNull($localized['guided_live_media_id']);
    }

    /**
     * @return array<string, array{0: string}>
     */
    public static function nonIntegerGuidedLiveMediaIdProvider(): array
    {
        return [
            'hex notation' => ['0x1a'],
            'exponent notation' => ['1e10'],
            'trailing decimal' => ['4211.0'],
            'digit separators' => ['1_000'],
            'blank' => [' '],
            'sign alone' => ['+'],
            'non-ascii digits' => ["\u{0664}\u{0662}"],
        ];
    }

    /**
     * Parity pin for js/admin/api/config.ts `normalizeAttachmentId`. The JS side
     * used `Number()`, which reads hex and exponent notation as valid ids that
     * this method has already refused -- so the browser could believe the demo
     * had a subject the server said it did not (rg-005). Both ends now run the
     * same decimal-digits predicate, and both ends pin the same table.
     *
     * @dataProvider nonIntegerGuidedLiveMediaIdProvider
     */
    public function testLocalizeSpaConfigRejectsIdsFilterValidateIntRejects(string $raw): void
    {
        $this->setOption('acx_guided_live_media_id', $raw);

        $this->invokePrivateMethod($this->admin, 'localize_spa_config', ['test-handle']);

        $localized = $GLOBALS['__ac_localized_scripts']['test-handle']['AltContextAdmin'] ?? null;

        $this->assertIsArray($localized);
        $this->assertNull($localized['guided_live_media_id'], sprintf('%s must not publish an id', $raw));
    }

    /**
     * @return array<string, array{0: string}>
     */
    public static function whitespacePaddedGuidedLiveMediaIdProvider(): array
    {
        return [
            'leading space' => [' 4211'],
            'trailing space' => ['4211 '],
            'both sides' => [' 4211 '],
            'explicit plus' => ['+4211'],
        ];
    }

    /**
     * @dataProvider whitespacePaddedGuidedLiveMediaIdProvider
     */
    public function testLocalizeSpaConfigAcceptsIdsFilterValidateIntAccepts(string $raw): void
    {
        $this->registerPost(4211, 'attachment');
        $this->setOption('acx_guided_live_media_id', $raw);

        $this->invokePrivateMethod($this->admin, 'localize_spa_config', ['test-handle']);

        $localized = $GLOBALS['__ac_localized_scripts']['test-handle']['AltContextAdmin'] ?? null;

        $this->assertIsArray($localized);
        $this->assertSame('4211', $localized['guided_live_media_id'], sprintf('%s must publish 4211', $raw));
    }

    /**
     * Every row in nonIntegerGuidedLiveMediaIdProvider ran with no attachment
     * registered, so the later attachment check refused them no matter what
     * the validator did: swapping FILTER_VALIDATE_INT for intval would coerce
     * '4211.0' to 4211 and '1e10' to ten billion and still publish null. These
     * rows seed the attachment each coercion would land on, so the validator
     * is the only thing left standing between the option and the payload.
     *
     * @return array<string, array{0: string, 1: int}>
     */
    public static function coercibleGuidedLiveMediaIdProvider(): array
    {
        return [
            'trailing decimal coerces to 4211' => ['4211.0', 4211],
            'exponent notation coerces to ten billion' => ['1e10', 10000000000],
            'digit separators coerce to 1' => ['1_000', 1],
            'leading zeros coerce to 1' => ['0001', 1],
            'signed leading zeros coerce to 1' => ['+0001', 1],
        ];
    }

    /**
     * @dataProvider coercibleGuidedLiveMediaIdProvider
     */
    public function testLocalizeSpaConfigRefusesCoercibleIdsEvenWhenThatAttachmentExists(
        string $raw,
        int $coercesTo
    ): void {
        $this->registerPost($coercesTo, 'attachment');
        $this->setOption('acx_guided_live_media_id', $raw);

        $this->invokePrivateMethod($this->admin, 'localize_spa_config', ['test-handle']);

        $localized = $GLOBALS['__ac_localized_scripts']['test-handle']['AltContextAdmin'] ?? null;

        $this->assertIsArray($localized);
        $this->assertNull(
            $localized['guided_live_media_id'],
            sprintf('%s must not publish attachment %d', $raw, $coercesTo)
        );
    }

    /**
     * PHP's FILTER_VALIDATE_INT trims exactly " \t\n\r\v". JavaScript's
     * String.prototype.trim is wider -- it also strips U+000C, NBSP and the
     * BOM -- so a padded id the publisher refused was read as a configured
     * subject in the browser. Both ends now pin the same padding set (rg-005).
     *
     * @return array<string, array{0: string}>
     */
    public static function nonPhpWhitespacePaddedGuidedLiveMediaIdProvider(): array
    {
        return [
            'form feed' => ["\u{000C}4211"],
            'no-break space' => ["\u{00A0}4211"],
            'byte order mark' => ["\u{FEFF}4211"],
        ];
    }

    /**
     * @dataProvider nonPhpWhitespacePaddedGuidedLiveMediaIdProvider
     */
    public function testLocalizeSpaConfigRejectsPaddingFilterValidateIntDoesNotTrim(string $raw): void
    {
        $this->registerPost(4211, 'attachment');
        $this->setOption('acx_guided_live_media_id', $raw);

        $this->invokePrivateMethod($this->admin, 'localize_spa_config', ['test-handle']);

        $localized = $GLOBALS['__ac_localized_scripts']['test-handle']['AltContextAdmin'] ?? null;

        $this->assertIsArray($localized);
        $this->assertNull($localized['guided_live_media_id'], sprintf('%s must not publish an id', $raw));
    }

    /**
     * U+000B is in PHP's trim set, so refusing it would invent a divergence
     * instead of closing one.
     */
    public function testLocalizeSpaConfigAcceptsVerticalTabPaddingLikeFilterValidateInt(): void
    {
        $this->registerPost(4211, 'attachment');
        $this->setOption('acx_guided_live_media_id', "\u{000B}4211");

        $this->invokePrivateMethod($this->admin, 'localize_spa_config', ['test-handle']);

        $localized = $GLOBALS['__ac_localized_scripts']['test-handle']['AltContextAdmin'] ?? null;

        $this->assertIsArray($localized);
        $this->assertSame('4211', $localized['guided_live_media_id']);
    }

    /**
     * @return array<string, array{0: string}>
     */
    public static function unsafeIntegerGuidedLiveMediaIdProvider(): array
    {
        return [
            'two to the fifty-third' => ['9007199254740992'],
            'php int max' => ['9223372036854775807'],
        ];
    }

    /**
     * filter_var accepts every integer up to PHP_INT_MAX, but the browser this
     * value is published to cannot hold one past 2^53 -- Number() silently
     * rounds it, so the id the panel would submit is not the id the operator
     * configured. The JS boundary already refuses these, which left the server
     * announcing a configured subject while the panel showed the live run off.
     * Publishing null makes both ends say the same thing (rg-005), and the
     * blocked line the panel already has is the right answer for an id it
     * cannot faithfully represent.
     *
     * @dataProvider unsafeIntegerGuidedLiveMediaIdProvider
     */
    public function testLocalizeSpaConfigRefusesIdsTheBrowserCannotRepresent(string $raw): void
    {
        $this->registerPost((int) $raw, 'attachment');
        $this->setOption('acx_guided_live_media_id', $raw);

        $this->invokePrivateMethod($this->admin, 'localize_spa_config', ['test-handle']);

        $localized = $GLOBALS['__ac_localized_scripts']['test-handle']['AltContextAdmin'] ?? null;

        $this->assertIsArray($localized);
        $this->assertNull($localized['guided_live_media_id'], sprintf('%s must not publish an id', $raw));
    }

    /**
     * The largest id both ends agree on still publishes, so the bound above is
     * a boundary and not a blanket refusal of large ids.
     */
    public function testLocalizeSpaConfigPublishesTheLargestIdBothEndsAgreeOn(): void
    {
        $this->registerPost(9007199254740991, 'attachment');
        $this->setOption('acx_guided_live_media_id', '9007199254740991');

        $this->invokePrivateMethod($this->admin, 'localize_spa_config', ['test-handle']);

        $localized = $GLOBALS['__ac_localized_scripts']['test-handle']['AltContextAdmin'] ?? null;

        $this->assertIsArray($localized);
        $this->assertSame('9007199254740991', $localized['guided_live_media_id']);
    }

    /**
     * @return array<string, array{0: mixed}>
     */
    public static function nonPositiveGuidedLiveMediaIdProvider(): array
    {
        return [
            'zero string' => ['0'],
            'zero int' => [0],
            'negative string' => ['-3'],
            'negative int' => [-3],
            'validator refusal' => ['0x1a'],
        ];
    }

    /**
     * The early `false === $id || $id <= 0` return is load-bearing on a real
     * admin screen and nothing pinned it. WordPress resolves an empty $post --
     * false, 0, '' -- from the global post, so with the guard removed
     * get_post_type(false) answers with whatever post the screen is showing;
     * when that is an attachment, the method publishes `false` or `0` as the
     * subject id. The global post here is that screen.
     *
     * @dataProvider nonPositiveGuidedLiveMediaIdProvider
     *
     * @param mixed $raw
     */
    public function testLocalizeSpaConfigRefusesNonPositiveIdsEvenBesideAGlobalAttachment($raw): void
    {
        $globalPost = new \stdClass();
        $globalPost->ID = 4211;
        $globalPost->post_type = 'attachment';
        $GLOBALS['post'] = $globalPost;

        try {
            $this->setOption('acx_guided_live_media_id', $raw);

            $this->invokePrivateMethod($this->admin, 'localize_spa_config', ['test-handle']);

            $localized = $GLOBALS['__ac_localized_scripts']['test-handle']['AltContextAdmin'] ?? null;

            $this->assertIsArray($localized);
            $this->assertNull(
                $localized['guided_live_media_id'],
                sprintf('%s must not publish an id', var_export($raw, true))
            );
        } finally {
            unset($GLOBALS['post']);
        }
    }
}
