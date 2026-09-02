<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Settings\RecognitionPolicy;
use AltContext\Tests\TestCase;

/**
 * @covers \AltContext\Settings\RecognitionPolicy
 */
class RecognitionPolicyTest extends TestCase
{
    public function testEnabledDefaultsToTrue(): void
    {
        $this->assertTrue(RecognitionPolicy::DEFAULT);
        $this->assertSame('acx_recognition_enabled', RecognitionPolicy::OPTION);
        $this->assertTrue(RecognitionPolicy::enabled());
    }

    public function testSetFalseMakesEnabledFalse(): void
    {
        $this->assertTrue(RecognitionPolicy::set(false));
        $this->assertFalse(RecognitionPolicy::enabled());
    }

    public function testStringZeroNormalisesToFalse(): void
    {
        $this->setOption(RecognitionPolicy::OPTION, '0');
        $this->assertFalse(RecognitionPolicy::enabled());
    }
}
