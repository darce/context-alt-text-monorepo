<?php

declare(strict_types=1);

namespace ContextAltText\Tests;

use PHPUnit\Framework\TestCase as PHPUnitTestCase;

/**
 * Base PHPUnit test case for Context Alt Text test suites.
 */
abstract class TestCase extends PHPUnitTestCase
{
    protected function setUp(): void
    {
        parent::setUp();
    }

    protected function tearDown(): void
    {
        parent::tearDown();
    }
}
