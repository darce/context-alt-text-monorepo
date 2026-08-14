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
 * R20-BR-09 / R19-BR-24 predicate: declaration-time deps (e.g. `use Trait`)
 * must be self-sufficient on the defining file. Loading the describe
 * controller first free-rides DescriptionHistoryService on
 * DescribeMediaService's sibling require_once of
 * trait-expects-meta-after-core-transforms.php. A history-first probe is the
 * only pin that catches deleting *only* the history service's require_once.
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

    /**
     * R20-BR-09: DescriptionHistoryService must load its trait when required
     * first in a fresh process with no Composer classmap in play. The describe
     * controller chain alone does not pin this — media service already
     * require_once's the same trait before history is reached.
     */
    public function testDescriptionHistoryServiceLoadsTraitWhenRequiredFirst(): void
    {
        $entrypoint = realpath(
            __DIR__ . '/../../src/api/services/class-description-history-service.php'
        );
        self::assertIsString($entrypoint, 'class-description-history-service.php must exist');

        $script = sprintf(
            'require %s; var_export(%s);',
            var_export($entrypoint, true),
            "class_exists('AltContext\\\\Api\\\\Services\\\\DescriptionHistoryService', false)"
            . " && trait_exists('AltContext\\\\Api\\\\Services\\\\ExpectsMetaAfterCoreTransforms', false)"
        );
        $output = shell_exec(sprintf('php -r %s 2>&1', escapeshellarg($script)));
        $this->assertSame(
            'true',
            trim((string) $output),
            sprintf(
                'history service must self-require ExpectsMetaAfterCoreTransforms when loaded first; got: %s',
                var_export($output, true)
            )
        );
    }
}
