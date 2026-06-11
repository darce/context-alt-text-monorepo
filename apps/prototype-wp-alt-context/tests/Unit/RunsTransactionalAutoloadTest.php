<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Tests\TestCase;

/**
 * rg-016 autoload parity for RunsTransactional.
 *
 * @covers \AltContext\Support\RunsTransactional
 */
class RunsTransactionalAutoloadTest extends TestCase
{
    public function testRunsTransactionalTraitIsLoadableViaComposerAutoloader(): void
    {
        $autoload = realpath(__DIR__ . '/../../vendor/autoload.php');
        self::assertIsString($autoload, 'vendor/autoload.php must exist for this test');

        $script = sprintf(
            'require %s; var_export(trait_exists("AltContext\\\\Support\\\\RunsTransactional"));',
            var_export($autoload, true),
        );
        $output = shell_exec(sprintf('php -r %s 2>&1', escapeshellarg($script)));
        $this->assertSame(
            'true',
            trim((string) $output),
            'AltContext\\Support\\RunsTransactional must be loadable via vendor/autoload.php in a fresh process; got: '
                . var_export($output, true)
                . '. If this fails, run `composer dump-autoload` inside apps/prototype-wp-alt-context.',
        );
    }

    public function testClusterMutationsControllerGuaranteesRunsTransactionalEvenWithStaleClassmap(): void
    {
        $controller = realpath(__DIR__ . '/../../src/api/class-cluster-mutations-controller.php');
        self::assertIsString($controller, 'class-cluster-mutations-controller.php must exist');

        $contents = file_get_contents($controller);
        $this->assertNotFalse($contents);
        $this->assertStringContainsString(
            "require_once __DIR__ . '/../support/trait-runs-transactional.php';",
            $contents,
            'cluster-mutations-controller must explicitly require RunsTransactional before service requires'
        );
    }
}