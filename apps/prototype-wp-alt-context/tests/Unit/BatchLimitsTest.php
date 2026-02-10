<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Support\BatchLimits;
use AltContext\Tests\TestCase;

/**
 * Tests for BatchLimits trait.
 *
 * @covers \AltContext\Support\BatchLimits
 */
class BatchLimitsTest extends TestCase
{
    private object $subject;

    protected function setUp(): void
    {
        parent::setUp();

        // Create anonymous class that uses the trait
	        $this->subject = new class() {
				use BatchLimits;

				// Expose protected methods for testing
				public function getTierBatchLimitFor(string $tier): int
				{
					return $this->get_tier_batch_limit_for($tier);
				}

				public function getCurrentTierBatchLimit(): int
				{
					return $this->get_current_tier_batch_limit();
				}
			};
    }

    /**
     * Test MVP batch limit is returned for all tiers.
     */
    public function testMvpBatchLimitReturnedForAllTiers(): void
    {
        $this->assertSame(10000, $this->subject->getTierBatchLimitFor('free'));
        $this->assertSame(10000, $this->subject->getTierBatchLimitFor('pro'));
        $this->assertSame(10000, $this->subject->getTierBatchLimitFor('business'));
        $this->assertSame(10000, $this->subject->getTierBatchLimitFor('enterprise'));
    }

    /**
     * Test unknown tier still returns MVP limit.
     */
    public function testUnknownTierReturnsMvpLimit(): void
    {
        $this->assertSame(10000, $this->subject->getTierBatchLimitFor('unknown_tier'));
    }

    /**
     * Test get_current_tier_batch_limit returns MVP limit.
     */
    public function testGetCurrentTierBatchLimitReturnsMvpLimit(): void
    {
        // Regardless of tier option, MVP always returns same limit
        $this->setOption('alt_context_tier', 'pro');
        $this->assertSame(10000, $this->subject->getCurrentTierBatchLimit());
    }

    /**
     * Test get_current_tier_batch_limit works without tier option set.
     */
    public function testGetCurrentTierBatchLimitDefaultsToMvpLimit(): void
    {
        // No tier option set
        $this->assertSame(10000, $this->subject->getCurrentTierBatchLimit());
    }
}
