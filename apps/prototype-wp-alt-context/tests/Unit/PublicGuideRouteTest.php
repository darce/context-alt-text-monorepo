<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

require_once __DIR__ . '/../../src/public/class-public-guide-route.php';

use AltContext\PublicSite\PublicGuideRoute;
use AltContext\Support\LifecycleManager;
use AltContext\Tests\TestCase;

final class PublicGuideRouteTest extends TestCase
{
    private const FALLBACK_COPY = 'The walkthrough could not load. Reload the page, or watch the recorded video on the case study page.';

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
    }

    public function testInitRegistersRewriteAndQueryVar(): void
    {
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

        $route->register_rewrite();

        self::assertSame(
            [
                [
                    'regex' => '^guide/?$',
                    'query' => 'index.php?acx_public_guide=1',
                    'after' => 'top',
                ],
            ],
            $GLOBALS['__ac_rewrite_rules']
        );

        $vars = $route->add_query_var(['s']);
        self::assertSame(['s', 'acx_public_guide'], $vars);
    }

    public function testDisabledOptionWithQueryVarReturns404Template(): void
    {
        $GLOBALS['__ac_query_vars']['acx_public_guide'] = '1';

        $route = new PublicGuideRoute($this->nullResolver());
        $result = $route->template_include('/theme/page.php');

        self::assertSame(404, $GLOBALS['__ac_status_header']);
        self::assertSame('/theme/404.php', $result);
        self::assertStringEndsNotWith('public-guide.php', $result);
    }

    public function testEnabledOptionReturnsStandaloneGuideTemplate(): void
    {
        $this->setOption('acx_public_guide_enabled', true);
        $GLOBALS['__ac_query_vars']['acx_public_guide'] = '1';

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
        self::assertStringNotContainsString('get_header(', $templateSource);
        self::assertStringNotContainsString('get_footer(', $templateSource);
    }

    public function testRequestWithoutQueryVarLeavesIncomingTemplateUntouched(): void
    {
        $this->setOption('acx_public_guide_enabled', true);

        $route = new PublicGuideRoute($this->nullResolver());
        $incoming = '/theme/single.php';

        self::assertSame($incoming, $route->template_include($incoming));
        self::assertNull($GLOBALS['__ac_status_header']);
    }

    public function testBundleFailureStillRendersFallbackAndEnqueuesNothing(): void
    {
        $this->setOption('acx_public_guide_enabled', true);
        $GLOBALS['__ac_query_vars']['acx_public_guide'] = '1';

        $route = new PublicGuideRoute($this->nullResolver());
        $route->init();
        $template = $route->template_include('/theme/page.php');
        do_action('wp_enqueue_scripts');

        self::assertSame(200, $GLOBALS['__ac_status_header']);
        self::assertSame([], $GLOBALS['__ac_scripts']);
        self::assertSame([], $GLOBALS['__ac_styles']);

        $html = $this->renderTemplate($template);
        self::assertStringContainsString('class="acx-public-guide__fallback"', $html);
        self::assertStringContainsString('role="alert"', $html);
        self::assertStringContainsString(self::FALLBACK_COPY, $html);
        self::assertStringContainsString('rel="canonical"', $html);
        self::assertStringContainsString('href="http://example.test/guide/"', $html);
    }

    public function testSuccessPathEnqueuesModuleScriptAndCssUrls(): void
    {
        $this->setOption('acx_public_guide_enabled', true);
        $GLOBALS['__ac_query_vars']['acx_public_guide'] = '1';

        $seen = [];
        $assets = [
            'js' => 'http://example.test/assets/guide.js',
            'css' => [
                'http://example.test/assets/guide-a.css',
                'http://example.test/assets/guide-b.css',
            ],
        ];
        $route = new PublicGuideRoute(
            static function (string $entry) use (&$seen, $assets): ?array {
                $seen[] = $entry;

                return $assets;
            }
        );
        $route->init();
        $route->template_include('/theme/page.php');
        do_action('wp_enqueue_scripts');

        self::assertSame(['js/guide/main.tsx'], $seen);
        self::assertArrayHasKey('acx-public-guide', $GLOBALS['__ac_scripts']);
        self::assertSame(
            'http://example.test/assets/guide.js',
            $GLOBALS['__ac_scripts']['acx-public-guide']['src']
        );
        self::assertTrue($GLOBALS['__ac_scripts']['acx-public-guide']['in_footer']);
        self::assertSame('module', $GLOBALS['__ac_scripts']['acx-public-guide']['data']['type']);
        self::assertSame(
            'http://example.test/assets/guide-a.css',
            $GLOBALS['__ac_styles']['acx-public-guide-0']['src']
        );
        self::assertSame(
            'http://example.test/assets/guide-b.css',
            $GLOBALS['__ac_styles']['acx-public-guide-1']['src']
        );
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
}
