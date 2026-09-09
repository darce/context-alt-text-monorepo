<?php

declare(strict_types=1);

namespace {
    if (!function_exists('wp_styles')) {
        function wp_styles(): object
        {
            $styles = new \stdClass();
            $styles->queue = array_keys($GLOBALS['__ac_styles'] ?? []);

            return $styles;
        }
    }

    if (!function_exists('wp_dequeue_style')) {
        function wp_dequeue_style($handle): void
        {
            unset($GLOBALS['__ac_styles'][$handle]);
        }
    }

    if (!function_exists('wp_dequeue_script')) {
        function wp_dequeue_script($handle): void
        {
            unset($GLOBALS['__ac_scripts'][$handle]);
        }
    }
}

namespace AltContext\Tests\Unit {

require_once __DIR__ . '/../../src/public/class-public-guide-route.php';

use AltContext\PublicSite\PublicGuideRoute;
use AltContext\Support\LifecycleManager;
use AltContext\Tests\TestCase;
use ReflectionMethod;
use stdClass;

final class PublicGuideRouteTest extends TestCase
{
    private const FALLBACK_COPY = 'The walkthrough could not load. Reload the page, or watch the recorded video on the case study page.';
    private const LOADING_COPY = 'Loading the walkthrough.';

    protected function setUp(): void
    {
        parent::setUp();
        if (!defined('ABSPATH')) {
            define('ABSPATH', sys_get_temp_dir() . '/');
        }

        $GLOBALS['__ac_rewrite_rules'] = [];
        $GLOBALS['__ac_query_vars'] = [];
        $GLOBALS['__ac_status_header'] = null;
        $GLOBALS['__ac_404_template'] = '/theme/404.php';
        $GLOBALS['__ac_home_url'] = 'http://example.test';
        $GLOBALS['__ac_wp_head_calls'] = 0;
        $GLOBALS['__ac_wp_footer_calls'] = 0;
        $GLOBALS['__ac_get_header_calls'] = 0;
        $GLOBALS['__ac_get_footer_calls'] = 0;
        unset($GLOBALS['wp'], $GLOBALS['wp_rewrite'], $GLOBALS['__ac_persisted_rewrite_rules']);
    }

    public function testInitDoesNotRegisterRewriteOrRequestHooksWhenDisabled(): void
    {
        $route = new PublicGuideRoute($this->nullResolver());
        $route->init();

        self::assertTrue(
            $this->hasHook($GLOBALS['__ac_actions']['init'][10] ?? [], [$route, 'register_rewrite']),
            'init() must still hook register_rewrite so a later enable can flush'
        );
        self::assertTrue(
            $this->hasHook(
                $GLOBALS['__ac_actions']['update_option_acx_public_guide_enabled'][10] ?? [],
                [$route, 'on_enabled_option_change']
            )
        );
        self::assertTrue(
            $this->hasHook(
                $GLOBALS['__ac_actions']['add_option_acx_public_guide_enabled'][10] ?? [],
                [$route, 'on_enabled_option_change']
            )
        );
        self::assertTrue(
            $this->hasHook(
                $GLOBALS['__ac_actions']['delete_option_acx_public_guide_enabled'][10] ?? [],
                [$route, 'on_enabled_option_change']
            )
        );
        self::assertFalse(
            $this->hasHook($GLOBALS['__ac_filters']['query_vars'][10] ?? [], [$route, 'add_query_var']),
            'disabled state must not register the public query var'
        );
        self::assertFalse(
            $this->hasHook($GLOBALS['__ac_filters']['template_include'][10] ?? [], [$route, 'template_include']),
            'disabled state must not hook template_include'
        );
        self::assertFalse(
            $this->hasHook($GLOBALS['__ac_actions']['wp_enqueue_scripts'][10] ?? [], [$route, 'enqueue_assets'])
        );
        self::assertFalse(
            $this->hasHook($GLOBALS['__ac_actions']['wp_enqueue_scripts'][100] ?? [], [$route, 'dequeue_theme_assets'])
        );

        $route->register_rewrite();
        self::assertSame([], $GLOBALS['__ac_rewrite_rules']);
    }

    public function testInitRegistersRewriteAndQueryVarWhenEnabled(): void
    {
        $this->setOption('acx_public_guide_enabled', true);
        $route = new PublicGuideRoute($this->nullResolver());
        $route->init();

        self::assertTrue(
            $this->hasHook($GLOBALS['__ac_actions']['init'][10] ?? [], [$route, 'register_rewrite']),
            'init() must register the rewrite on init'
        );
        self::assertTrue(
            $this->hasHook($GLOBALS['__ac_filters']['query_vars'][10] ?? [], [$route, 'add_query_var']),
            'init() must add the acx_public_guide query var'
        );
        self::assertTrue(
            $this->hasHook($GLOBALS['__ac_filters']['template_include'][10] ?? [], [$route, 'template_include']),
            'init() must handle the route via template_include'
        );
        self::assertTrue(
            $this->hasHook($GLOBALS['__ac_actions']['wp_enqueue_scripts'][10] ?? [], [$route, 'enqueue_assets'])
        );
        self::assertTrue(
            $this->hasHook($GLOBALS['__ac_actions']['wp_enqueue_scripts'][100] ?? [], [$route, 'dequeue_theme_assets'])
        );

        $route->register_rewrite();

        self::assertSame(
            [
                [
                    'regex' => PublicGuideRoute::REWRITE_REGEX,
                    'query' => 'index.php?acx_public_guide=1',
                    'after' => 'top',
                ],
            ],
            $GLOBALS['__ac_rewrite_rules']
        );

        $vars = $route->add_query_var(['s']);
        self::assertSame(['s', 'acx_public_guide'], $vars);
    }

    public function testDisabledOptionLeavesIncomingTemplateUntouched(): void
    {
        $this->simulateRewriteMatch();

        $route = new PublicGuideRoute($this->nullResolver());
        $incoming = '/theme/page.php';
        $result = $route->template_include($incoming);

        self::assertSame($incoming, $result);
        self::assertNull($GLOBALS['__ac_status_header']);
    }

    public function testEnabledOptionReturnsStandaloneGuideTemplate(): void
    {
        $this->setOption('acx_public_guide_enabled', true);
        $this->simulateRewriteMatch();

        $route = new PublicGuideRoute($this->nullResolver());
        $result = $route->template_include('/theme/page.php');

        self::assertSame(200, $GLOBALS['__ac_status_header']);
        self::assertSame($this->expectedTemplatePath(), $result);

        $html = $this->renderTemplate($result);
        $templateSource = (string) file_get_contents($result);

        self::assertStringContainsString('rel="canonical"', $html);
        self::assertStringContainsString('href="http://example.test/guide/"', $html);
        self::assertSame(1, $GLOBALS['__ac_wp_head_calls']);
        self::assertSame(1, $GLOBALS['__ac_wp_footer_calls']);
        self::assertSame(0, $GLOBALS['__ac_get_header_calls']);
        self::assertSame(0, $GLOBALS['__ac_get_footer_calls']);
        self::assertStringContainsString('id="acx-public-guide"', $html);
        self::assertStringContainsString('data-scope="recorded"', $html);
        self::assertStringContainsString('data-example="bundled"', $html);
        self::assertStringContainsString('class="acx-public-guide__loading"', $html);
        self::assertStringContainsString('aria-live="polite"', $html);
        self::assertStringContainsString(self::LOADING_COPY, $html);
        self::assertStringContainsString('data-acx-load-timeout="' . PublicGuideRoute::LOAD_TIMEOUT_MS . '"', $html);
        self::assertStringNotContainsString('get_header(', $templateSource);
        self::assertStringNotContainsString('get_footer(', $templateSource);
    }

    public function testRequestWithoutRewriteMatchLeavesIncomingTemplateUntouched(): void
    {
        $this->setOption('acx_public_guide_enabled', true);

        $route = new PublicGuideRoute($this->nullResolver());
        $incoming = '/theme/single.php';

        self::assertSame($incoming, $route->template_include($incoming));
        self::assertNull($GLOBALS['__ac_status_header']);
    }

    /**
     * @dataProvider provideEnabledFlags
     */
    public function testQueryVarSpoofOnOtherPathDoesNot404OrDequeue(bool $enabled): void
    {
        if ($enabled) {
            $this->setOption('acx_public_guide_enabled', true);
        }

        $this->simulateQueryVarSpoof();
        $GLOBALS['__ac_styles']['theme-style'] = ['src' => 'http://example.test/theme.css'];
        $GLOBALS['__ac_scripts']['theme-script'] = ['src' => 'http://example.test/theme.js'];

        $route = new PublicGuideRoute($this->nullResolver());
        $incoming = '/theme/page.php';
        $result = $route->template_include($incoming);

        self::assertSame($incoming, $result);
        self::assertNull($GLOBALS['__ac_status_header']);
        self::assertFalse($this->isPublicGuideRequest($route));

        $route->dequeue_theme_assets();
        self::assertArrayHasKey('theme-style', $GLOBALS['__ac_styles']);
        self::assertArrayHasKey('theme-script', $GLOBALS['__ac_scripts']);

        $route->enqueue_assets();
        self::assertArrayNotHasKey('acx-public-guide', $GLOBALS['__ac_scripts']);
        self::assertArrayNotHasKey('acx-public-guide-watch', $GLOBALS['__ac_scripts']);
    }

    /**
     * @return array<string, array{0: bool}>
     */
    public static function provideEnabledFlags(): array
    {
        return [
            'option off' => [false],
            'option on' => [true],
        ];
    }

    public function testGuideRouteSweepKeepsPluginAndCoreChromeHandles(): void
    {
        $this->setOption('acx_public_guide_enabled', true);
        $this->simulateRewriteMatch();
        $GLOBALS['__ac_styles']['theme-style'] = ['src' => 'http://example.test/theme.css'];
        $GLOBALS['__ac_styles']['some-other-plugin'] = ['src' => 'http://example.test/other.css'];
        $GLOBALS['__ac_styles']['admin-bar'] = ['src' => 'http://example.test/admin-bar.css'];
        $GLOBALS['__ac_styles']['dashicons'] = ['src' => 'http://example.test/dashicons.css'];
        $GLOBALS['__ac_styles']['acx-public-guide-0'] = ['src' => 'http://example.test/guide.css'];
        $GLOBALS['__ac_scripts']['theme-script'] = ['src' => 'http://example.test/theme.js'];
        $GLOBALS['__ac_scripts']['admin-bar'] = ['src' => 'http://example.test/admin-bar.js'];
        $GLOBALS['__ac_scripts']['acx-public-guide'] = ['src' => 'http://example.test/guide.js'];

        $route = new PublicGuideRoute($this->nullResolver());
        $route->dequeue_theme_assets();

        $styleHandles = array_keys($GLOBALS['__ac_styles']);
        sort($styleHandles);
        self::assertSame(['acx-public-guide-0', 'admin-bar', 'dashicons'], $styleHandles);

        $scriptHandles = array_keys($GLOBALS['__ac_scripts']);
        sort($scriptHandles);
        self::assertSame(['acx-public-guide', 'admin-bar'], $scriptHandles);
    }

    public function testGuideRouteSweepStripsUnknownCoreHandles(): void
    {
        $this->setOption('acx_public_guide_enabled', true);
        $this->simulateRewriteMatch();
        $GLOBALS['__ac_styles']['theme-style'] = ['src' => 'http://example.test/theme.css'];
        $GLOBALS['__ac_styles']['wp-block-library'] = ['src' => 'http://example.test/wp-block-library.css'];
        $GLOBALS['__ac_styles']['admin-bar'] = ['src' => 'http://example.test/admin-bar.css'];
        $GLOBALS['__ac_styles']['dashicons'] = ['src' => 'http://example.test/dashicons.css'];
        $GLOBALS['__ac_styles']['acx-public-guide-0'] = ['src' => 'http://example.test/guide.css'];
        $GLOBALS['__ac_scripts']['theme-script'] = ['src' => 'http://example.test/theme.js'];
        $GLOBALS['__ac_scripts']['wp-block-library'] = ['src' => 'http://example.test/wp-block-library.js'];
        $GLOBALS['__ac_scripts']['admin-bar'] = ['src' => 'http://example.test/admin-bar.js'];
        $GLOBALS['__ac_scripts']['acx-public-guide'] = ['src' => 'http://example.test/guide.js'];

        $route = new PublicGuideRoute($this->nullResolver());
        $route->dequeue_theme_assets();

        self::assertArrayNotHasKey('wp-block-library', $GLOBALS['__ac_styles']);
        self::assertArrayNotHasKey('wp-block-library', $GLOBALS['__ac_scripts']);

        $styleHandles = array_keys($GLOBALS['__ac_styles']);
        sort($styleHandles);
        self::assertSame(['acx-public-guide-0', 'admin-bar', 'dashicons'], $styleHandles);

        $scriptHandles = array_keys($GLOBALS['__ac_scripts']);
        sort($scriptHandles);
        self::assertSame(['acx-public-guide', 'admin-bar'], $scriptHandles);
    }

    public function testEnabledOptionChangeRegistersRewrite(): void
    {
        $route = new PublicGuideRoute($this->nullResolver());
        $route->init();
        self::assertSame([], $GLOBALS['__ac_rewrite_rules']);

        $this->setOption('acx_public_guide_enabled', true);
        $route->on_enabled_option_change();

        self::assertSame(
            [
                [
                    'regex' => PublicGuideRoute::REWRITE_REGEX,
                    'query' => 'index.php?acx_public_guide=1',
                    'after' => 'top',
                ],
            ],
            $GLOBALS['__ac_rewrite_rules']
        );
    }

    public function testDisabledOptionChangeDropsRewriteFromExtraRulesTop(): void
    {
        $wpRewrite = new stdClass();
        $wpRewrite->extra_rules_top = [
            PublicGuideRoute::REWRITE_REGEX => 'index.php?acx_public_guide=1',
            '^other/?$' => 'index.php?pagename=other',
        ];
        // phpcs:ignore WordPress.WP.GlobalVariablesOverride.Prohibited -- unit-test rewrite object
        $GLOBALS['wp_rewrite'] = $wpRewrite;

        $route = new PublicGuideRoute($this->nullResolver());
        $route->on_enabled_option_change();

        self::assertSame(
            ['^other/?$' => 'index.php?pagename=other'],
            $wpRewrite->extra_rules_top
        );
        self::assertSame([], $GLOBALS['__ac_rewrite_rules']);
        self::assertSame(
            ['^other/?$' => 'index.php?pagename=other'],
            $GLOBALS['__ac_persisted_rewrite_rules']
        );
        self::assertArrayNotHasKey(PublicGuideRoute::REWRITE_REGEX, $GLOBALS['__ac_persisted_rewrite_rules']);
    }

    public function testOptionDeleteDropsRewriteFromPersistedRules(): void
    {
        $this->setOption('acx_public_guide_enabled', true);
        $wpRewrite = new stdClass();
        $wpRewrite->extra_rules_top = [
            PublicGuideRoute::REWRITE_REGEX => 'index.php?acx_public_guide=1',
            '^other/?$' => 'index.php?pagename=other',
        ];
        // phpcs:ignore WordPress.WP.GlobalVariablesOverride.Prohibited -- unit-test rewrite object
        $GLOBALS['wp_rewrite'] = $wpRewrite;

        $route = new PublicGuideRoute($this->nullResolver());
        $route->init();
        delete_option('acx_public_guide_enabled');

        self::assertSame(
            ['^other/?$' => 'index.php?pagename=other'],
            $wpRewrite->extra_rules_top
        );
        self::assertSame(
            ['^other/?$' => 'index.php?pagename=other'],
            $GLOBALS['__ac_persisted_rewrite_rules']
        );
        self::assertArrayNotHasKey(PublicGuideRoute::REWRITE_REGEX, $GLOBALS['__ac_persisted_rewrite_rules']);
    }

    public function testDeactivateDropsRewriteFromPersistedRules(): void
    {
        $wpRewrite = new stdClass();
        $wpRewrite->extra_rules_top = [
            PublicGuideRoute::REWRITE_REGEX => 'index.php?acx_public_guide=1',
            '^other/?$' => 'index.php?pagename=other',
        ];
        // phpcs:ignore WordPress.WP.GlobalVariablesOverride.Prohibited -- unit-test rewrite object
        $GLOBALS['wp_rewrite'] = $wpRewrite;

        (new LifecycleManager())->deactivate();

        self::assertSame(
            ['^other/?$' => 'index.php?pagename=other'],
            $wpRewrite->extra_rules_top
        );
        self::assertSame(
            ['^other/?$' => 'index.php?pagename=other'],
            $GLOBALS['__ac_persisted_rewrite_rules']
        );
        self::assertArrayNotHasKey(PublicGuideRoute::REWRITE_REGEX, $GLOBALS['__ac_persisted_rewrite_rules']);
    }

    public function testBundleFailureStillRendersFallbackAndEnqueuesNothing(): void
    {
        $this->setOption('acx_public_guide_enabled', true);
        $this->simulateRewriteMatch();

        $route = new PublicGuideRoute($this->nullResolver());
        $route->init();
        $template = $route->template_include('/theme/page.php');
        do_action('wp_enqueue_scripts');

        self::assertSame(200, $GLOBALS['__ac_status_header']);
        self::assertSame([], $GLOBALS['__ac_scripts']);
        self::assertSame([], $GLOBALS['__ac_styles']);

        $html = $this->renderTemplate($template);
        self::assertStringContainsString('class="acx-public-guide__loading"', $html);
        self::assertStringContainsString('aria-live="polite"', $html);
        self::assertStringContainsString(self::LOADING_COPY, $html);
        self::assertStringContainsString('class="acx-public-guide__fallback"', $html);
        self::assertStringContainsString('role="alert"', $html);
        self::assertStringContainsString('hidden', $html);
        self::assertStringContainsString(self::FALLBACK_COPY, $html);
        self::assertDoesNotMatchRegularExpression('/<script(?![^>]*\\bsrc=)/', $html);
        self::assertStringContainsString('rel="canonical"', $html);
        self::assertStringContainsString('href="http://example.test/guide/"', $html);
    }

    public function testSuccessPathEnqueuesModuleScriptAndCssUrls(): void
    {
        $this->setOption('acx_public_guide_enabled', true);
        $this->simulateRewriteMatch();

        $seen = [];
        $assets = [
            'js' => 'http://example.test/assets/guide.js',
            'css' => [
                'http://example.test/assets/guide-a.css',
                'http://example.test/assets/guide-b.css',
            ],
        ];
        $watchAssets = [
            'js' => 'http://example.test/assets/guide-watch.js',
            'css' => [],
        ];
        $route = new PublicGuideRoute(
            static function (string $entry) use (&$seen, $assets, $watchAssets): ?array {
                $seen[] = $entry;
                if (PublicGuideRoute::WATCH_ENTRY_POINT === $entry) {
                    return $watchAssets;
                }

                return $assets;
            }
        );
        $route->init();
        $route->template_include('/theme/page.php');
        do_action('wp_enqueue_scripts');

        self::assertSame(
            [PublicGuideRoute::WATCH_ENTRY_POINT, PublicGuideRoute::ENTRY_POINT],
            $seen
        );
        self::assertSame(
            [PublicGuideRoute::WATCH_SCRIPT_HANDLE, PublicGuideRoute::SCRIPT_HANDLE],
            array_keys($GLOBALS['__ac_scripts'])
        );
        self::assertArrayHasKey('acx-public-guide', $GLOBALS['__ac_scripts']);
        self::assertSame(
            'http://example.test/assets/guide.js',
            $GLOBALS['__ac_scripts']['acx-public-guide']['src']
        );
        self::assertTrue($GLOBALS['__ac_scripts']['acx-public-guide']['in_footer']);
        self::assertSame('module', $GLOBALS['__ac_scripts']['acx-public-guide']['data']['type']);
        self::assertArrayHasKey('acx-public-guide-watch', $GLOBALS['__ac_scripts']);
        self::assertSame(
            'http://example.test/assets/guide-watch.js',
            $GLOBALS['__ac_scripts']['acx-public-guide-watch']['src']
        );
        self::assertTrue($GLOBALS['__ac_scripts']['acx-public-guide-watch']['in_footer']);
        self::assertSame('module', $GLOBALS['__ac_scripts']['acx-public-guide-watch']['data']['type']);
        self::assertSame(
            'http://example.test/assets/guide-a.css',
            $GLOBALS['__ac_styles']['acx-public-guide-0']['src']
        );
        self::assertSame(
            'http://example.test/assets/guide-b.css',
            $GLOBALS['__ac_styles']['acx-public-guide-1']['src']
        );
    }

    public function testWatchScriptEnqueuesWhenGuideBundleIsMissing(): void
    {
        $this->setOption('acx_public_guide_enabled', true);
        $this->simulateRewriteMatch();

        $route = new PublicGuideRoute(
            static function (string $entry): ?array {
                if (PublicGuideRoute::WATCH_ENTRY_POINT === $entry) {
                    return [
                        'js' => 'http://example.test/assets/guide-watch.js',
                        'css' => [],
                    ];
                }

                return null;
            }
        );
        $route->init();
        $route->template_include('/theme/page.php');
        do_action('wp_enqueue_scripts');

        self::assertArrayHasKey('acx-public-guide-watch', $GLOBALS['__ac_scripts']);
        self::assertArrayNotHasKey('acx-public-guide', $GLOBALS['__ac_scripts']);
        self::assertSame('module', $GLOBALS['__ac_scripts']['acx-public-guide-watch']['data']['type']);
        self::assertTrue($GLOBALS['__ac_scripts']['acx-public-guide-watch']['in_footer']);
    }

    public function testRewriteUpgradeFlushesOnceWhenVersionDiverges(): void
    {
        $this->setOption('acx_rewrite_version', 'old');
        $manager = new class() extends LifecycleManager {
            public int $flushCount = 0;

            protected function flush_rewrites(): void
            {
                ++$this->flushCount;
                parent::flush_rewrites();
            }
        };

        do_action('init');
        self::assertSame(1, $manager->flushCount);
        self::assertSame(LifecycleManager::REWRITE_VERSION, get_option('acx_rewrite_version'));

        do_action('init');
        self::assertSame(1, $manager->flushCount);
    }

    public function testRewriteUpgradeDoesNotFlushWhenVersionMatches(): void
    {
        $this->setOption('acx_rewrite_version', LifecycleManager::REWRITE_VERSION);
        $manager = new class() extends LifecycleManager {
            public int $flushCount = 0;

            protected function flush_rewrites(): void
            {
                ++$this->flushCount;
            }
        };

        do_action('init');
        self::assertSame(0, $manager->flushCount);
    }

    public function testPluginBootstrapRequiresAndInitsPublicGuideRoute(): void
    {
        $source = (string) file_get_contents(__DIR__ . '/../../src/class-alt-context.php');

        self::assertStringContainsString(
            "require_once __DIR__ . '/public/class-public-guide-route.php';",
            $source
        );
        self::assertStringContainsString('( new PublicGuideRoute() )->init();', $source);
    }

    public function testIsEnabledAcceptsOnlyTruthyOptionValues(): void
    {
        self::assertFalse(PublicGuideRoute::is_enabled());

        $this->setOption('acx_public_guide_enabled', true);
        self::assertTrue(PublicGuideRoute::is_enabled());

        $this->setOption('acx_public_guide_enabled', 1);
        self::assertTrue(PublicGuideRoute::is_enabled());

        $this->setOption('acx_public_guide_enabled', '1');
        self::assertTrue(PublicGuideRoute::is_enabled());

        $this->setOption('acx_public_guide_enabled', 'true');
        self::assertFalse(PublicGuideRoute::is_enabled());
    }

    /**
     * @param list<array{callback:mixed,accepted_args:int}> $entries
     */
    private function hasHook(array $entries, mixed $callback): bool
    {
        foreach ($entries as $entry) {
            if (($entry['callback'] ?? null) === $callback) {
                return true;
            }
        }

        return false;
    }

    /**
     * @return callable(string): ?array{js: string, css: list<string>}
     */
    private function nullResolver(): callable
    {
        return static fn (string $entry): ?array => null;
    }

    private function expectedTemplatePath(): string
    {
        $path = realpath(__DIR__ . '/../../src/public/templates/public-guide.php');
        if (is_string($path) && '' !== $path) {
            return $path;
        }

        return __DIR__ . '/../../src/public/templates/public-guide.php';
    }

    private function renderTemplate(string $path): string
    {
        ob_start();
        include $path;

        return (string) ob_get_clean();
    }

    private function simulateRewriteMatch(): void
    {
        $GLOBALS['__ac_query_vars'][PublicGuideRoute::QUERY_VAR] = '1';
        // phpcs:ignore WordPress.WP.GlobalVariablesOverride.Prohibited -- simulate rewrite-matched request
        $GLOBALS['wp'] = (object) ['matched_rule' => PublicGuideRoute::REWRITE_REGEX];
    }

    private function simulateQueryVarSpoof(): void
    {
        $GLOBALS['__ac_query_vars'][PublicGuideRoute::QUERY_VAR] = '1';
        // phpcs:ignore WordPress.WP.GlobalVariablesOverride.Prohibited -- simulate GET query-var spoof
        $GLOBALS['wp'] = (object) ['matched_rule' => '(.?.+?)(?:/([0-9]+))?/?$'];
    }

    private function isPublicGuideRequest(PublicGuideRoute $route): bool
    {
        $method = new ReflectionMethod(PublicGuideRoute::class, 'is_public_guide_request');
        $method->setAccessible(true);

        return (bool) $method->invoke($route);
    }
}

}
