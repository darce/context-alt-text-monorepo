<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Tests\TestCase;

/**
 * Regression for E21-12B (rg-016).
 *
 * The admin page classes live under src/admin/class-*.php (WordPress filename
 * convention). Per rg-016 they are not PSR-4 autoloadable and reach production
 * only through the Composer classmap, which goes stale on any checkout that
 * adds a class without re-running `composer dump-autoload`. When
 * class-retention-page.php shipped (E21-12) without a fresh dump, alt_context()
 * fatally errored on `new RetentionPage()` for every request — front end and
 * wp-admin alike — because Menu is constructed unconditionally on
 * plugins_loaded. The fix is an explicit require_once block in the entrypoint.
 *
 * @covers \AltContext\Admin\Menu
 */
class AdminPageAutoloadTest extends TestCase
{
    /** Admin classes instantiated on the plugins_loaded bootstrap path. */
    private const ADMIN_BOOTSTRAP_CLASSES = [
        'AbstractSpaPage',
        'DashboardPage',
        'WorkbenchPage',
        'RosterPage',
        'SettingsPage',
        'DescriptionHistoryPage',
        'RetentionPage',
        'Menu',
    ];

    /** Require lines the entrypoint must carry, in dependency order. */
    private const REQUIRED_ENTRYPOINT_LINES = [
        "require_once ACX_PLUGIN_DIR . 'src/admin/class-abstract-spa-page.php';",
        "require_once ACX_PLUGIN_DIR . 'src/admin/class-dashboard-page.php';",
        "require_once ACX_PLUGIN_DIR . 'src/admin/class-workbench-page.php';",
        "require_once ACX_PLUGIN_DIR . 'src/admin/class-roster-page.php';",
        "require_once ACX_PLUGIN_DIR . 'src/admin/class-settings-page.php';",
        "require_once ACX_PLUGIN_DIR . 'src/admin/class-description-history-page.php';",
        "require_once ACX_PLUGIN_DIR . 'src/admin/class-retention-page.php';",
        "require_once ACX_PLUGIN_DIR . 'src/admin/class-menu.php';",
    ];

    public function testAdminPageClassesAreLoadableViaComposerAutoloader(): void
    {
        $autoload = realpath(__DIR__ . '/../../vendor/autoload.php');
        self::assertIsString($autoload, 'vendor/autoload.php must exist for this test');

        foreach (self::ADMIN_BOOTSTRAP_CLASSES as $class) {
            $fqcn = 'AltContext\\Admin\\' . $class;
            $script = sprintf(
                'require %s; var_export(class_exists(%s));',
                var_export($autoload, true),
                var_export($fqcn, true),
            );
            $output = trim((string) shell_exec(sprintf('php -r %s 2>&1', escapeshellarg($script))));
            $this->assertSame(
                'true',
                $output,
                sprintf(
                    '%s must be loadable via vendor/autoload.php in a fresh process; got: %s. '
                        . 'If this fails, run `composer dump-autoload` inside apps/prototype-wp-alt-context.',
                    $fqcn,
                    var_export($output, true),
                ),
            );
        }
    }

    public function testEntrypointExplicitlyRequiresAdminPageClasses(): void
    {
        // Defense-in-depth: guarantees the durable fix stays. Each admin page
        // class must be require_once'd in alt-context.php so a stale classmap
        // cannot fatal a request before dispatch.
        $entrypoint = realpath(__DIR__ . '/../../alt-context.php');
        self::assertIsString($entrypoint, 'alt-context.php must exist');

        $contents = (string) file_get_contents($entrypoint);

        foreach (self::REQUIRED_ENTRYPOINT_LINES as $line) {
            $this->assertStringContainsString(
                $line,
                $contents,
                'alt-context.php must explicitly require every admin page class after vendor/autoload.php: '
                    . $line,
            );
        }
    }

    public function testAdminBootstrapLoadsWithoutTheClassmap(): void
    {
        // The strongest guard: prove the require block alone loads the whole
        // admin bootstrap surface with NO autoloader present (a maximally-stale
        // classmap), and that Menu — which default-constructs RetentionPage,
        // the class that fataled — instantiates. class_exists autoload flag is
        // false so only the explicit require lines can satisfy it.
        $pluginDir = realpath(__DIR__ . '/../..');
        self::assertIsString($pluginDir);

        $requires = '';
        foreach (self::REQUIRED_ENTRYPOINT_LINES as $line) {
            // Reuse the exact entrypoint lines with ACX_PLUGIN_DIR bound to the plugin root.
            $requires .= str_replace('ACX_PLUGIN_DIR . ', var_export($pluginDir . '/', true) . ' . ', $line) . "\n";
        }

        $checks = '';
        foreach (self::ADMIN_BOOTSTRAP_CLASSES as $class) {
            $checks .= sprintf(
                'if (!class_exists(%s, false)) { fwrite(STDERR, %s); exit(1); }' . "\n",
                var_export('AltContext\\Admin\\' . $class, true),
                var_export($class . ' not loaded', true),
            );
        }

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
            'The alt-context.php admin require block must load every admin bootstrap class and construct '
                . 'Menu (which default-constructs RetentionPage) with no autoloader present; got: '
                . var_export($output, true),
        );
    }
}
