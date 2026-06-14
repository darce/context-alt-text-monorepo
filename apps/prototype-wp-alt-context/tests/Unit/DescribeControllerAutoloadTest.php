<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Tests\TestCase;

use function escapeshellarg;
use function realpath;
use function shell_exec;
use function sprintf;
use function trim;
use function var_export;

/**
 * rg-016: the new describe `class-*.php` / `interface-*.php` files use
 * WordPress-style filenames that are NOT PSR-4 autoloadable. They are wired
 * through an explicit require_once chain from the controller header block, so
 * the runtime classes must resolve even WITHOUT a fresh `composer
 * dump-autoload`. Requiring only the controller entrypoint must pull in the
 * host interface and media service via that chain.
 *
 * @coversNothing
 */
class DescribeControllerAutoloadTest extends TestCase
{
    public function testDescribeChainLoadsWithoutComposerDumpAutoload(): void
    {
        $entrypoint = realpath(__DIR__ . '/../../src/api/class-describe-controller.php');
        self::assertIsString($entrypoint, 'class-describe-controller.php must exist');

        $script = sprintf(
            'require %s; var_export(%s);',
            var_export($entrypoint, true),
            "class_exists('AltContext\\\\Api\\\\DescribeController')"
            . " && interface_exists('AltContext\\\\Api\\\\DescribeHostInterface')"
            . " && class_exists('AltContext\\\\Api\\\\Services\\\\DescribeMediaService')"
            // rg-016: the service's Telemetry dependency must resolve through the
            // require_once chain too, not free-ride on a freshly-dumped classmap.
            . " && class_exists('AltContext\\\\Support\\\\Telemetry')"
        );
        $output = shell_exec(sprintf('php -r %s 2>&1', escapeshellarg($script)));
        $this->assertSame(
            'true',
            trim((string) $output),
            sprintf('describe require_once chain must self-resolve; got: %s', var_export($output, true))
        );
    }
}
