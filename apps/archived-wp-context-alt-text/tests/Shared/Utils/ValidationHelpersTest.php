<?php

declare(strict_types=1);

namespace ContextAltText\Tests\Shared\Utils;

use ContextAltText\Shared\Utils\ValidationHelpers;
use ContextAltText\Tests\TestCase;

/**
 * Test case for ValidationHelpers.
 *
 * @covers \ContextAltText\Shared\Utils\ValidationHelpers
 */
class ValidationHelpersTest extends TestCase
{
    /**
     * @dataProvider provideSanitizeUrlData
     */
    public function testSanitizeUrl(string $url, bool $stripTrailingSlash, string $expected): void
    {
        $result = ValidationHelpers::sanitizeUrl($url, $stripTrailingSlash);
        $this->assertSame($expected, $result);
    }

    public function provideSanitizeUrlData(): array
    {
        return [
            // Valid URLs
            'simple http' => ['http://example.com', false, 'http://example.com'],
            'simple https' => ['https://example.com', false, 'https://example.com'],
            'with path' => ['http://example.com/path', false, 'http://example.com/path'],
            'with query' => ['http://example.com?key=value', false, 'http://example.com?key=value'],
            'with fragment' => ['http://example.com#section', false, 'http://example.com#section'],
            'with port' => ['http://example.com:8080', false, 'http://example.com:8080'],

            // Trailing slash handling
            'with trailing slash no strip' => ['http://example.com/', false, 'http://example.com/'],
            'with trailing slash strip' => ['http://example.com/', true, 'http://example.com'],
            'no trailing slash no strip' => ['http://example.com', false, 'http://example.com'],
            'no trailing slash strip' => ['http://example.com', true, 'http://example.com'],
            'path with trailing slash strip' => ['http://example.com/path/', true, 'http://example.com/path'],

            // Whitespace handling
            'with leading space' => ['  http://example.com', false, 'http://example.com'],
            'with trailing space' => ['http://example.com  ', false, 'http://example.com'],
            'with both spaces' => ['  http://example.com  ', false, 'http://example.com'],

            // Invalid URLs
            'empty string' => ['', false, ''],
            'whitespace only' => ['   ', false, ''],
            'not a url' => ['not-a-url', false, ''],
            'missing protocol' => ['example.com', false, ''],
            'invalid protocol' => ['javascript:alert(1)', false, ''],
            'relative path' => ['/path/to/page', false, ''],
        ];
    }

    /**
     * @dataProvider provideSanitizeTimeoutData
     */
    public function testSanitizeTimeout(int $value, int $min, int $max, int $expected): void
    {
        $result = ValidationHelpers::sanitizeTimeout($value, $min, $max);
        $this->assertSame($expected, $result);
    }

    public function provideSanitizeTimeoutData(): array
    {
        return [
            // Within range
            'within range' => [5000, 0, 10000, 5000],
            'at minimum' => [0, 0, 10000, 0],
            'at maximum' => [10000, 0, 10000, 10000],

            // Below minimum
            'below minimum' => [-100, 0, 10000, 0],
            'way below minimum' => [-99999, 1000, 10000, 1000],

            // Above maximum
            'above maximum' => [15000, 0, 10000, 10000],
            'way above maximum' => [999999, 0, 10000, 10000],

            // Edge cases
            'zero range at zero' => [0, 0, 0, 0],
            'negative range' => [-50, -100, -10, -50],
            'large range' => [50000, 1000, 100000, 50000],
        ];
    }

    public function testSanitizeBoolDelegates(): void
    {
        // Verify it delegates to SanitizationHelpers
        $this->assertTrue(ValidationHelpers::sanitizeBool(true));
        $this->assertFalse(ValidationHelpers::sanitizeBool(false));
        $this->assertTrue(ValidationHelpers::sanitizeBool(1));
        $this->assertFalse(ValidationHelpers::sanitizeBool(0));
        $this->assertTrue(ValidationHelpers::sanitizeBool('true'));
        $this->assertFalse(ValidationHelpers::sanitizeBool('false'));
    }
}
