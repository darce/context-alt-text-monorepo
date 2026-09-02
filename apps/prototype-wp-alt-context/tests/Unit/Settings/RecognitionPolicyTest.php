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
        $this->assertNull(get_option(RecognitionPolicy::OPTION, null));
        $this->assertTrue(RecognitionPolicy::enabled());
    }

    public function testSetFalseOnFreshInstallPersistsZeroString(): void
    {
        $this->assertNull(get_option(RecognitionPolicy::OPTION, null));
        $this->assertTrue(RecognitionPolicy::set(false));
        $this->assertSame('0', get_option(RecognitionPolicy::OPTION));
        $this->assertFalse(RecognitionPolicy::enabled());
    }

    public function testSetTruePersistsOneString(): void
    {
        $this->assertTrue(RecognitionPolicy::set(true));
        $this->assertSame('1', get_option(RecognitionPolicy::OPTION));
        $this->assertTrue(RecognitionPolicy::enabled());
    }

    public function testSetFalseMakesEnabledFalse(): void
    {
        $this->assertTrue(RecognitionPolicy::set(false));
        $this->assertFalse(RecognitionPolicy::enabled());
        $this->assertSame('0', get_option(RecognitionPolicy::OPTION));
    }

    public function testSetReturnsFalseWhenWriteDoesNotLand(): void
    {
        $GLOBALS['__ac_update_option_fail'] = [RecognitionPolicy::OPTION => true];

        $this->assertFalse(RecognitionPolicy::set(false));
        $this->assertNull(get_option(RecognitionPolicy::OPTION, null));
        $this->assertTrue(RecognitionPolicy::enabled());
    }

    public function testStringZeroNormalisesToFalse(): void
    {
        $this->setOption(RecognitionPolicy::OPTION, '0');
        $this->assertFalse(RecognitionPolicy::enabled());
    }

    /**
     * @dataProvider knownTrueProvider
     */
    public function testNormalizeKnownTrueForms(mixed $value): void
    {
        $this->assertTrue(RecognitionPolicy::normalize($value));
    }

    /**
     * @return array<string, array{0: mixed}>
     */
    public static function knownTrueProvider(): array
    {
        return [
            'bool_true' => [true],
            'int_one' => [1],
            'string_one' => ['1'],
            'string_true' => ['true'],
            'string_TRUE' => ['TRUE'],
        ];
    }

    /**
     * Unknown / falsey stored forms fail closed. DEFAULT is not applied here —
     * it applies only when the option row is missing.
     *
     * @dataProvider failClosedStoredProvider
     */
    public function testNormalizeFailClosedForUnknownAndFalseyValues(mixed $value): void
    {
        $this->assertFalse(
            RecognitionPolicy::normalize($value),
            'normalize(' . var_export($value, true) . ') must not fail-open to DEFAULT'
        );
    }

    /**
     * @return array<string, array{0: mixed}>
     */
    public static function failClosedStoredProvider(): array
    {
        return [
            'bool_false' => [false],
            'string_false' => ['false'],
            'int_zero' => [0],
            'string_zero' => ['0'],
            'empty_string' => [''],
            'no' => ['no'],
            'yes' => ['yes'],
            'off' => ['off'],
            'on' => ['on'],
            'int_two' => [2],
            'null_stored' => [null],
        ];
    }

    /**
     * @dataProvider failClosedStoredProvider
     */
    public function testEnabledIsFalseForStoredNonTrueValues(mixed $value): void
    {
        if (null === $value) {
            $this->markTestSkipped('get_option coalesces stored null to missing; DEFAULT applies');
        }
        $this->setOption(RecognitionPolicy::OPTION, $value);
        $this->assertFalse(
            RecognitionPolicy::enabled(),
            'stored ' . var_export($value, true) . ' must not fail-open'
        );
    }
}
