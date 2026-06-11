<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Tests\TestCase;
use ReflectionMethod;

class ClustersReadFixtureRegenGuardTest extends TestCase
{
    public function testAssertGoldenHasClustersReadFixtureRegenGuard(): void
    {
        $method = new ReflectionMethod(ClustersControllerCharacterizationTest::class, 'assertGolden');
        $source = file_get_contents($method->getFileName());
        $this->assertIsString($source);

        $lines = explode("\n", $source);
        $methodBody = implode(
            "\n",
            array_slice($lines, $method->getStartLine() - 1, $method->getEndLine() - $method->getStartLine() + 1)
        );

        $this->assertStringContainsString("getenv('UPDATE_CLUSTERS_READ_FIXTURES')", $methodBody);
        $this->assertStringContainsString('file_put_contents($responseFixture', $methodBody);
        $this->assertStringContainsString('file_put_contents($sideEffectsFixture', $methodBody);
    }
}