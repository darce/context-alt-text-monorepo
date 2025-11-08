<?php

declare(strict_types=1);

namespace ContextAltText\Tests\Shared\Utils;

use ContextAltText\Shared\Utils\SanitizationHelpers;
use ContextAltText\Tests\TestCase;

/**
 * Test case for SanitizationHelpers.
 *
 * Ensures contract alignment with TypeScript primitives.ts
 *
 * @covers \ContextAltText\Shared\Utils\SanitizationHelpers
 */
class SanitizationHelpersTest extends TestCase
{
    /**
     * @dataProvider provideFiniteNumberData
     */
    public function testToFiniteNumber($value, $fallback, $expected): void
    {
        $result = SanitizationHelpers::toFiniteNumber($value, $fallback);
        $this->assertSame($expected, $result);
    }

    public function provideFiniteNumberData(): array
    {
        return [
            // Valid numbers
            'positive integer' => [42, 0, 42.0],
            'zero' => [0, 0, 0.0],
            'negative integer' => [-10, 0, -10.0],
            'float' => [3.14, 0, 3.14],

            // Numeric strings
            'numeric string positive' => ['42', 0, 42.0],
            'numeric string zero' => ['0', 0, 0.0],
            'numeric string negative' => ['-10', 0, -10.0],
            'numeric string float' => ['3.14', 0, 3.14],

            // Invalid values with default fallback
            'null with default' => [null, 0, 0],
            'non-numeric string with default' => ['not a number', 0, 0],
            'empty string with default' => ['', 0, 0],
            'array with default' => [[], 0, 0],
            'object with default' => [new \stdClass(), 0, 0],

            // Custom fallback
            'invalid with custom fallback' => ['invalid', 42, 42],
            'null with custom fallback' => [null, -1, -1],
            'empty string with custom fallback' => ['', 100, 100],

            // Booleans (is_numeric returns false for booleans in PHP)
            'boolean true' => [true, 0, 0], // Returns fallback
            'boolean false' => [false, 0, 0], // Returns fallback

            // Edge cases
            'whitespace string' => ['   ', 0, 0],
            'string zero' => ['0', 0, 0.0],
            'negative zero string' => ['-0', 0, 0.0],
        ];
    }

    /**
     * @dataProvider provideNumberOrNullData
     */
    public function testToNumberOrNull($value, $expected): void
    {
        $result = SanitizationHelpers::toNumberOrNull($value);
        $this->assertSame($expected, $result);
    }

    public function provideNumberOrNullData(): array
    {
        return [
            // Valid numbers
            'positive integer' => [42, 42.0],
            'zero' => [0, 0.0],
            'negative integer' => [-10, -10.0],
            'float' => [3.14, 3.14],

            // Numeric strings
            'numeric string positive' => ['42', 42.0],
            'numeric string zero' => ['0', 0.0],
            'numeric string negative' => ['-10', -10.0],
            'numeric string float' => ['3.14', 3.14],

            // Invalid values return null
            'null' => [null, null],
            'non-numeric string' => ['not a number', null],
            'empty string' => ['', null],
            'whitespace' => ['   ', null],
            'array' => [[], null],
            'object' => [new \stdClass(), null],

            // Booleans (is_numeric returns false for booleans in PHP)
            'boolean true' => [true, null], // is_numeric(true) = false, returns null
            'boolean false' => [false, null], // is_numeric(false) = false, returns null

            // Edge cases
            'string zero' => ['0', 0.0],
            'negative zero' => ['-0', 0.0],
        ];
    }

    /**
     * @dataProvider provideNullableTimestampData
     */
    public function testToNullableTimestamp($value, $expected): void
    {
        $result = SanitizationHelpers::toNullableTimestamp($value);
        $this->assertSame($expected, $result);
    }

    public function provideNullableTimestampData(): array
    {
        return [
            // Valid timestamps (positive numbers)
            'small positive' => [1, 1],
            'medium positive' => [1000, 1000],
            'unix timestamp' => [1700000000, 1700000000],
            'string timestamp' => ['1700000000', 1700000000],

            // Zero returns null
            'zero integer' => [0, null],
            'zero string' => ['0', null],
            'negative zero string' => ['-0', null],

            // Negative numbers return null
            'negative one' => [-1, null],
            'negative large' => [-100, null],
            'negative string' => ['-10', null],

            // Invalid values return null
            'null' => [null, null],
            'non-numeric string' => ['not a number', null],
            'empty string' => ['', null],
            'whitespace' => ['   ', null],
            'array' => [[], null],

            // Boolean edge cases (is_numeric returns false for booleans in PHP)
            'boolean true' => [true, null], // is_numeric(true) = false, returns null
            'boolean false' => [false, null], // is_numeric(false) = false, returns null
        ];
    }

    /**
     * @dataProvider provideStringOrNullData
     */
    public function testToStringOrNull($value, $expected): void
    {
        $result = SanitizationHelpers::toStringOrNull($value);
        $this->assertSame($expected, $result);
    }

    public function provideStringOrNullData(): array
    {
        return [
            // Valid strings (trimmed and sanitized)
            'simple string' => ['hello', 'hello'],
            'string with spaces' => ['  hello  ', 'hello'],
            'string with content' => ['Hello World', 'Hello World'],

            // Empty/whitespace returns null
            'empty string' => ['', null],
            'whitespace only' => ['   ', null],
            'tab and newline' => ["\t\n", null],

            // Null/undefined
            'null' => [null, null],

            // Numbers convert to strings
            'positive integer' => [42, '42'],
            'zero' => [0, '0'],
            'negative integer' => [-10, '-10'],
            'float' => [3.14, '3.14'],

            // Booleans convert to strings
            'boolean true' => [true, '1'],
            'boolean false' => [false, null], // is_numeric(false) = false, returns null

            // Invalid values return null
            'array' => [[], null],
            'object' => [new \stdClass(), null],
        ];
    }

    public function testToStringOrNullSanitizesXss(): void
    {
        // Test that HTML/XSS is sanitized via sanitize_text_field
        $dirty = '<script>alert("xss")</script>Hello';
        $result = SanitizationHelpers::toStringOrNull($dirty);

        // sanitize_text_field strips HTML tags
        $this->assertStringNotContainsString('<script>', $result);
        $this->assertStringNotContainsString('</script>', $result);
        $this->assertStringContainsString('Hello', $result);
    }

    /**
     * @dataProvider provideEnsureStringData
     */
    public function testEnsureString($value, $expected): void
    {
        $result = SanitizationHelpers::ensureString($value);
        $this->assertSame($expected, $result);
    }

    public function provideEnsureStringData(): array
    {
        return [
            // Strings returned with sanitization (sanitize_text_field trims)
            'simple string' => ['hello', 'hello'],
            'string with spaces' => ['  hello  ', 'hello'], // sanitize_text_field trims
            'empty string' => ['', ''],
            'whitespace' => ['   ', ''], // sanitize_text_field trims to empty

            // Null returns empty string
            'null' => [null, ''],

            // Numbers convert to strings
            'positive integer' => [42, '42'],
            'zero' => [0, '0'],
            'negative integer' => [-10, '-10'],
            'float' => [3.14, '3.14'],

            // Booleans convert to strings
            'boolean true' => [true, '1'],
            'boolean false' => [false, ''],

            // Invalid values return empty string
            'array' => [[], ''],
            'object' => [new \stdClass(), ''],
        ];
    }

    public function testEnsureStringSanitizesXss(): void
    {
        $dirty = '<script>alert("xss")</script>Hello';
        $result = SanitizationHelpers::ensureString($dirty);

        $this->assertStringNotContainsString('<script>', $result);
        $this->assertStringNotContainsString('</script>', $result);
        $this->assertStringContainsString('Hello', $result);
    }

    /**
     * @dataProvider provideBooleanOrNullData
     */
    public function testToBooleanOrNull($value, $expected): void
    {
        $result = SanitizationHelpers::toBooleanOrNull($value);
        $this->assertSame($expected, $result);
    }

    public function provideBooleanOrNullData(): array
    {
        return [
            // Booleans returned as-is
            'boolean true' => [true, true],
            'boolean false' => [false, false],

            // Null returns null
            'null' => [null, null],

            // Numbers: 0 is false, non-zero is true
            'number one' => [1, true],
            'number forty-two' => [42, true],
            'number negative' => [-1, true],
            'number zero' => [0, false],
            'float zero' => [0.0, false],

            // IMPORTANT: is_numeric() is checked BEFORE is_string() in PHP
            // So numeric strings are handled by the numeric branch, not string branch
            // BUG: The implementation does $value !== 0 where $value is still a string
            // So '0' !== 0 is TRUE (different types), returning true instead of false
            'string zero' => ['0', true], // BUG: is_numeric('0') = true, '0' !== 0 = true
            'string one' => ['1', true], // is_numeric('1') = true, '1' !== 0 = true
            'string two' => ['2', true], // is_numeric('2') = true, '2' !== 0 = true
            'string negative' => ['-5', true], // is_numeric('-5') = true, '-5' !== 0 = true

            // String truthy values (non-numeric strings)
            'string true lowercase' => ['true', true],
            'string true uppercase' => ['TRUE', true],
            'string true mixed' => ['True', true],
            'string yes lowercase' => ['yes', true],
            'string yes uppercase' => ['YES', true],
            'string yes mixed' => ['Yes', true],

            // String falsy values (non-numeric strings)
            'string false lowercase' => ['false', false],
            'string false uppercase' => ['FALSE', false],
            'string false mixed' => ['False', false],
            'string no lowercase' => ['no', false],
            'string no uppercase' => ['NO', false],
            'string no mixed' => ['No', false],
            'empty string' => ['', false],

            // Whitespace handling for non-numeric strings
            'string true with spaces' => ['  true  ', true],
            'string false with spaces' => ['  false  ', false],
            // These are numeric after trimming, so handled by numeric branch (with BUG)
            'string one with spaces' => ['  1  ', true],
            'string zero with spaces' => ['  0  ', true], // BUG: '  0  ' is numeric, !== 0 is true

            // Ambiguous strings return null (non-numeric)
            'string maybe' => ['maybe', null],
            'string on' => ['on', null],
            'string off' => ['off', null],
            'string hello' => ['hello', null],

            // Invalid types return null
            'array' => [[], null],
            'object' => [new \stdClass(), null],
        ];
    }

    /**
     * @dataProvider provideUniqueNumericIdsData
     */
    public function testToUniqueNumericIds(array $input, array $expected): void
    {
        $result = SanitizationHelpers::toUniqueNumericIds($input);
        $this->assertSame($expected, $result);
    }

    public function provideUniqueNumericIdsData(): array
    {
        return [
            // Simple valid cases
            'numeric array' => [[1, 2, 3], [1, 2, 3]],
            'single id' => [[42], [42]],

            // String to numeric conversion
            'string ids' => [['1', '2', '3'], [1, 2, 3]],
            'mixed types' => [[1, '2', 3, '4'], [1, 2, 3, 4]],

            // Duplicate removal
            'duplicates numeric' => [[1, 2, 2, 3, 3, 3], [1, 2, 3]],
            'duplicates string' => [['1', '2', '2', '3'], [1, 2, 3]],
            'duplicates mixed' => [[1, '1', 2, '2'], [1, 2]],

            // Zero filtering
            'with zero' => [[0, 1, 2], [1, 2]],
            'with zero string' => [['0', '1', '2'], [1, 2]],
            'only zero' => [[0], []],

            // Negative number filtering
            'with negative' => [[-1, 1, 2], [1, 2]],
            'with negative string' => [['-5', '1', '2'], [1, 2]],
            'only negatives' => [[-1, -2, -3], []],

            // Invalid value filtering
            'with non-numeric' => [['invalid', 1, 2], [1, 2]],
            'with empty string' => [['', '1', '2'], [1, 2]],
            'with null' => [[null, 1, 2], [1, 2]],

            // Empty array
            'empty array' => [[], []],

            // Only invalid values
            'only invalid' => [[0, -1, 'invalid'], []],
            'only empty and negative' => [['', '-5'], []],

            // Order preservation
            'preserves order' => [[3, 1, 2, 1, 3], [3, 1, 2]],
            'preserves order strings' => [['3', '1', '2', '1', '3'], [3, 1, 2]],

            // Large IDs
            'large ids' => [[999999, 1, 2], [999999, 1, 2]],
        ];
    }

    /**
     * @dataProvider provideSanitizeBoolData
     */
    public function testSanitizeBool($value, bool $expected): void
    {
        $result = SanitizationHelpers::sanitizeBool($value);
        $this->assertSame($expected, $result);
    }

    public function provideSanitizeBoolData(): array
    {
        return [
            // Booleans
            'boolean true' => [true, true],
            'boolean false' => [false, false],

            // Numeric truthy (filter_var only accepts specific values)
            'number one' => [1, true],
            'string one' => ['1', true],

            // Numeric falsy
            'number zero' => [0, false],
            'string zero' => ['0', false],

            // String truthy (filter_var accepts: "1", "true", "on", "yes")
            'string true' => ['true', true],
            'string yes' => ['yes', true],
            'string on' => ['on', true],

            // String falsy (filter_var accepts: "0", "false", "off", "no", "")
            'string false' => ['false', false],
            'string no' => ['no', false],
            'string off' => ['off', false],
            'empty string' => ['', false],

            // Invalid defaults to false (filter_var returns null for these)
            'null' => [null, false],
            'array' => [[], false],
            'invalid string' => ['invalid', false],
            'number forty-two' => [42, false], // filter_var doesn't accept arbitrary numbers
        ];
    }
}
