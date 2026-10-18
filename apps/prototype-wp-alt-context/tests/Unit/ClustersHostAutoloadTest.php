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
        $this->assertSymbolLoadableViaComposerClassmap('interface_exists', 'AltContext\\Api\\ClustersHostInterface');
    }

    public function testClusterResponseEnvelopeServiceIsLoadableViaComposerClassmap(): void
    {
        $this->assertSymbolLoadableViaComposerClassmap('class_exists', 'AltContext\\Api\\Services\\ClusterResponseEnvelopeService');
    }

    public function testClusterProjectionSyncServiceIsLoadableViaComposerClassmap(): void
    {
        $this->assertSymbolLoadableViaComposerClassmap('class_exists', 'AltContext\\Api\\Services\\ClusterProjectionSyncService');
    }

    public function testClusterReadServiceIsLoadableViaComposerClassmap(): void
    {
        $this->assertSymbolLoadableViaComposerClassmap('class_exists', 'AltContext\\Api\\Services\\ClusterReadService');
    }

    public function testClusterReadDependenciesIsLoadableViaComposerClassmap(): void
    {
        $this->assertSymbolLoadableViaComposerClassmap('class_exists', 'AltContext\\Api\\Services\\ClusterReadDependencies');
    }

    public function testClusterReadConfigIsLoadableViaComposerClassmap(): void
    {
        $this->assertSymbolLoadableViaComposerClassmap('class_exists', 'AltContext\\Api\\Services\\ClusterReadConfig');
    }

    private function assertSymbolLoadableViaComposerClassmap(string $exists_fn, string $symbol): void
    {
        $autoload = realpath(__DIR__ . '/../../vendor/autoload.php');
        self::assertIsString($autoload, 'vendor/autoload.php must exist for this test');

        $script = sprintf(
            'require %s; var_export(%s(%s));',
            var_export($autoload, true),
            $exists_fn,
            var_export($symbol, true),
        );
        $output = shell_exec(sprintf('php -r %s 2>&1', escapeshellarg($script)));
        $this->assertSame(
            'true',
            trim((string) $output),
            sprintf('%s must be loadable via vendor/autoload.php classmap; got: %s', $symbol, var_export($output, true))
        );
    }
}
