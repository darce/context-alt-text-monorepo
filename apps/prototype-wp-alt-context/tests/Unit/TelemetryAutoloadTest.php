<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Tests\TestCase;

/**
 * Regression for E15-11-BR-13.
 *
 * The Telemetry class lives at src/support/class-telemetry.php (WordPress
 * filename convention). Per rg-016, classes in that scheme are not PSR-4
 * autoloadable; they rely on the Composer classmap, which can be stale
 * after `git pull` until `composer dump-autoload` runs. This test runs the
 * runtime check the BR-13 reviewer cited (loading vendor/autoload.php in a
 * fresh PHP process and asserting class_exists), verifying that the
 * production autoload path resolves the class without depending on the
 * test-suite's custom kebab-case fallback autoloader.
 *
 * @covers \AltContext\Support\Telemetry
 */
class TelemetryAutoloadTest extends TestCase
{
    public function testTelemetryClassIsLoadableViaComposerAutoloader(): void
    {
        $autoload = realpath(__DIR__ . '/../../vendor/autoload.php');
        self::assertIsString($autoload, 'vendor/autoload.php must exist for this test');

        $script = sprintf(
            'require %s; var_export(class_exists("AltContext\\\\Support\\\\Telemetry"));',
            var_export($autoload, true),
        );
        $output = shell_exec(sprintf('php -r %s 2>&1', escapeshellarg($script)));
        $this->assertSame(
            'true',
            trim((string) $output),
            'AltContext\\Support\\Telemetry must be loadable via vendor/autoload.php in a fresh process; got: '
                . var_export($output, true)
                . '. If this fails, run `composer dump-autoload` inside apps/prototype-wp-alt-context to '
                . 'rebuild the classmap.',
        );
    }

    public function testPluginEntrypointGuaranteesTelemetryEvenWithStaleClassmap(): void
    {
        // Defense-in-depth: the plugin entrypoint (alt-context.php) does an
        // explicit require_once on Telemetry after loading vendor/autoload.php.
        // That guarantees production has the class even if the classmap is
        // stale (e.g. fresh `git pull` without `composer dump-autoload`).
        $entrypoint = realpath(__DIR__ . '/../../alt-context.php');
        self::assertIsString($entrypoint, 'alt-context.php must exist');

        $contents = file_get_contents($entrypoint);
        $this->assertNotFalse($contents);
        $this->assertStringContainsString(
            "require_once ACX_PLUGIN_DIR . 'src/support/class-telemetry.php';",
            $contents,
            'alt-context.php must explicitly require Telemetry after vendor/autoload.php so a stale '
                . 'classmap does not fatal a request before dispatch'
        );
    }
}
