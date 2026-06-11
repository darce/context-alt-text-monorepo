<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Tests\TestCase;

/**
 * @coversNothing
 */
class ClustersHostAutoloadTest extends TestCase
{
    public function testClustersHostInterfaceIsLoadableViaComposerClassmap(): void
    {
        $autoload = realpath(__DIR__ . '/../../vendor/autoload.php');
        self::assertIsString($autoload, 'vendor/autoload.php must exist for this test');

        $script = sprintf(
            'require %s; var_export(interface_exists("AltContext\\\\Api\\\\ClustersHostInterface"));',
            var_export($autoload, true),
        );
        $output = shell_exec(sprintf('php -r %s 2>&1', escapeshellarg($script)));
        $this->assertSame(
            'true',
            trim((string) $output),
            'ClustersHostInterface must be loadable via vendor/autoload.php classmap; got: ' . var_export($output, true)
        );
    }
}
