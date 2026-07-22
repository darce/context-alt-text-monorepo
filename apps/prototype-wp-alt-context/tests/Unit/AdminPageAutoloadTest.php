<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Tests\TestCase;

/**
 * Regression for E21-12B (rg-016).
 *
 * The bootstrap classes below are constructed unconditionally by alt_context()
 * on plugins_loaded but use the WordPress class-*.php filename convention, so
 * they reach production only through the Composer classmap — which goes stale on
 * any checkout that adds a class without re-running `composer dump-autoload`.
 * When class-retention-page.php shipped (E21-12) without a fresh dump,
 * alt_context() fatally errored on `new RetentionPage()` (inside the Menu
 * constructor) for every request, front end and wp-admin alike, because none of
 * these admin classes self-require their dependencies. The fix is an explicit
 * require_once block in the entrypoint.
 *
 * Scope note: Api and LifecycleManager are intentionally NOT in this set — they
 * self-require their own dependency chains, and hardening their entry files
 * would eagerly load the sync/repository subsystem on every request. See the
 * comment on the require block in alt-context.php.
 *
 * @covers \AltContext\Admin\Menu
 */
class AdminPageAutoloadTest extends TestCase
{
    /**
     * Bootstrap classes made classmap-independent by the entrypoint block,
     * as fully-qualified names (the trait is checked separately).
     */
    private const BOOTSTRAP_CLASSES = [
        'AltContext\\Admin\\AbstractSpaPage',
        'AltContext\\Admin\\DashboardPage',
        'AltContext\\Admin\\WorkbenchPage',
        'AltContext\\Admin\\RosterPage',
        'AltContext\\Admin\\SettingsPage',
        'AltContext\\Admin\\DescriptionHistoryPage',
        'AltContext\\Admin\\RetentionPage',
        'AltContext\\Admin\\Menu',
        'AltContext\\Admin\\Admin',
        'AltContext\\Admin\\AttachmentFields',
        'AltContext\\Api\\XmpEmbedController',
        'AltContext\\Media\\XmpPersistenceFactory',
    ];

    private const BOOTSTRAP_TRAIT = 'AltContext\\Support\\BatchLimits';

    /**
     * Require lines the entrypoint must carry, in dependency order
     * (trait before Admin, AbstractSpaPage before its subclasses). Relative to
     * ACX_PLUGIN_DIR.
     */
    private const REQUIRED_ENTRYPOINT_PATHS = [
        'src/support/trait-batch-limits.php',
        'src/media/class-xmp-persistence-factory.php',
        'src/api/class-xmp-embed-controller.php',
        'src/admin/class-admin.php',
        'src/admin/class-attachment-fields.php',
        'src/admin/class-abstract-spa-page.php',
        'src/admin/class-dashboard-page.php',
        'src/admin/class-workbench-page.php',
        'src/admin/class-roster-page.php',
        'src/admin/class-settings-page.php',
        'src/admin/class-description-history-page.php',
        'src/admin/class-retention-page.php',
        'src/admin/class-menu.php',
    ];

    public function testBootstrapClassesAreLoadableViaComposerAutoloader(): void
    {
        $autoload = realpath(__DIR__ . '/../../vendor/autoload.php');
        self::assertIsString($autoload, 'vendor/autoload.php must exist for this test');

        $symbols = array_merge(self::BOOTSTRAP_CLASSES, [self::BOOTSTRAP_TRAIT]);
        foreach ($symbols as $symbol) {
            $script = sprintf(
                'require %s; var_export(class_exists(%s) || trait_exists(%s));',
                var_export($autoload, true),
                var_export($symbol, true),
                var_export($symbol, true),
            );
            $output = trim((string) shell_exec(sprintf('php -r %s 2>&1', escapeshellarg($script))));
            $this->assertSame(
                'true',
                $output,
                sprintf(
                    '%s must be loadable via vendor/autoload.php in a fresh process; got: %s. '
                        . 'If this fails, run `composer dump-autoload` inside apps/prototype-wp-alt-context.',
                    $symbol,
                    var_export($output, true),
                ),
            );
        }
    }

    public function testEntrypointExplicitlyRequiresBootstrapClasses(): void
    {
        // Defense-in-depth: guarantees the durable fix stays. Every fragile
        // bootstrap class must be require_once'd in alt-context.php so a stale
        // classmap cannot fatal a request before dispatch.
        $entrypoint = realpath(__DIR__ . '/../../alt-context.php');
        self::assertIsString($entrypoint, 'alt-context.php must exist');

        $contents = (string) file_get_contents($entrypoint);

        foreach (self::REQUIRED_ENTRYPOINT_PATHS as $path) {
            $line = sprintf("require_once ACX_PLUGIN_DIR . '%s';", $path);
            $this->assertStringContainsString(
                $line,
                $contents,
                'alt-context.php must explicitly require every fragile bootstrap class: ' . $line,
            );
        }
    }

    public function testBootstrapLoadsWithoutTheClassmap(): void
    {
        // The strongest guard: prove the require block alone loads the whole
        // fragile bootstrap surface with NO autoloader present (a maximally
        // stale classmap), and that Menu — which default-constructs
        // RetentionPage, the class that fataled — instantiates. class_exists /
        // trait_exists use autoload=false so only the explicit require lines can
        // satisfy them. (This set is self-contained by construction; Api and
        // LifecycleManager are excluded precisely because their self-require
        // chains depend on the autoloader — see alt-context.php.)
        $pluginDir = realpath(__DIR__ . '/../..');
        self::assertIsString($pluginDir);

        $requires = '';
        foreach (self::REQUIRED_ENTRYPOINT_PATHS as $path) {
            $requires .= sprintf('require_once %s;' . "\n", var_export($pluginDir . '/' . $path, true));
        }

        $checks = '';
        foreach (self::BOOTSTRAP_CLASSES as $fqcn) {
            $checks .= sprintf(
                'if (!class_exists(%s, false)) { fwrite(STDERR, %s); exit(1); }' . "\n",
                var_export($fqcn, true),
                var_export($fqcn . ' not loaded', true),
            );
        }
        $checks .= sprintf(
            'if (!trait_exists(%s, false)) { fwrite(STDERR, %s); exit(1); }' . "\n",
            var_export(self::BOOTSTRAP_TRAIT, true),
            var_export(self::BOOTSTRAP_TRAIT . ' not loaded', true),
        );

        $script = "<?php\n" . $requires . $checks
            . 'new AltContext\\Admin\\Menu('
            . 'new AltContext\\Admin\\DashboardPage(), new AltContext\\Admin\\WorkbenchPage(), '
            . 'new AltContext\\Admin\\RosterPage(), new AltContext\\Admin\\SettingsPage());' . "\n"
            . 'echo "ok";' . "\n";

        $tmp = tempnam(sys_get_temp_dir(), 'acx_autoload_');
        self::assertIsString($tmp);
        file_put_contents($tmp, $script);
        $output = trim((string) shell_exec(sprintf('php %s 2>&1', escapeshellarg($tmp))));
        unlink($tmp);

        $this->assertSame(
            'ok',
            $output,
            'The alt-context.php bootstrap require block must load every fragile bootstrap class and '
                . 'construct Menu (which default-constructs RetentionPage) with no autoloader present; got: '
                . var_export($output, true),
        );
    }
}
