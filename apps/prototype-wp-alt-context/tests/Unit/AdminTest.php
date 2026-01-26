<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Admin\Admin;
use AltContext\Tests\TestCase;
use ReflectionClass;

/**
 * Tests for Admin class.
 *
 * @covers \AltContext\Admin\Admin
 */
class AdminTest extends TestCase
{
    private Admin $admin;

    protected function setUp(): void
    {
        parent::setUp();
        $this->admin = new Admin();
    }

    /**
     * Test get_tier returns valid tier from option.
     */
    public function testGetTierReturnsValidTierFromOption(): void
    {
        $this->setOption('alt_context_tier', 'pro');

        $tier = $this->invokePrivateMethod($this->admin, 'get_tier');

        $this->assertSame('pro', $tier);
    }

    /**
     * Test get_tier returns free as default.
     */
    public function testGetTierReturnsFreAsDefault(): void
    {
        // No tier option set
        $tier = $this->invokePrivateMethod($this->admin, 'get_tier');

        $this->assertSame('free', $tier);
    }

    /**
     * Test get_tier falls back to free for invalid tier.
     */
    public function testGetTierFallsBackToFreeForInvalidTier(): void
    {
        $this->setOption('alt_context_tier', 'invalid_tier_name');

        $tier = $this->invokePrivateMethod($this->admin, 'get_tier');

        $this->assertSame('free', $tier);
    }

    /**
     * Test get_tier with all valid tiers.
     *
     * @dataProvider validTierProvider
     */
    public function testGetTierWithValidTiers(string $tierName): void
    {
        $this->setOption('alt_context_tier', $tierName);

        $tier = $this->invokePrivateMethod($this->admin, 'get_tier');

        $this->assertSame($tierName, $tier);
    }

    /**
     * @return array<array{string}>
     */
    public static function validTierProvider(): array
    {
        return [
            ['free'],
            ['pro'],
            ['business'],
            ['enterprise'],
        ];
    }

    /**
     * Test get_tier sanitizes input.
     */
    public function testGetTierSanitizesInput(): void
    {
        // sanitize_key lowercases and removes special chars
        $this->setOption('alt_context_tier', 'PRO');

        $tier = $this->invokePrivateMethod($this->admin, 'get_tier');

        $this->assertSame('pro', $tier);
    }

    /**
     * Helper to invoke private/protected methods.
     */
    private function invokePrivateMethod(object $object, string $methodName, array $args = []): mixed
    {
        $reflection = new ReflectionClass($object);
        $method = $reflection->getMethod($methodName);
        $method->setAccessible(true);
        return $method->invokeArgs($object, $args);
    }
}
