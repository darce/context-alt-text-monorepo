<?php

declare(strict_types=1);

namespace ContextAltText\Shared\Utils;

use function filter_var;
use function max;
use function min;
use function rtrim;
use function trim;

use const FILTER_VALIDATE_URL;

/**
 * Reusable validation helpers.
 *
 * For type sanitization/coercion, use SanitizationHelpers instead.
 */
final class ValidationHelpers
{
    /**
     * Sanitize and validate a URL string.
     *
     * @param string $url The URL to sanitize
     * @param bool $stripTrailingSlash Whether to remove trailing slash
     * @return string Empty string if invalid, sanitized URL otherwise
     */
    public static function sanitizeUrl(string $url, bool $stripTrailingSlash = false): string
    {
        $url = trim($url);

        if ($url === '' || filter_var($url, FILTER_VALIDATE_URL) === false) {
            return '';
        }

        return $stripTrailingSlash ? rtrim($url, '/') : $url;
    }

    /**
     * Clamp a timeout value to a safe range.
     *
     * @param int $value The timeout value in milliseconds
     * @param int $min Minimum allowed value
     * @param int $max Maximum allowed value
     * @return int Clamped timeout value
     */
    public static function sanitizeTimeout(int $value, int $min, int $max): int
    {
        return max($min, min($max, $value));
    }

    /**
     * Convert mixed value to boolean with strict validation.
     *
     * @deprecated Use SanitizationHelpers::sanitizeBool() or SanitizationHelpers::toBooleanOrNull() instead
     * @param mixed $value Value to convert to boolean
     * @return bool Sanitized boolean value
     */
    public static function sanitizeBool($value): bool
    {
        return SanitizationHelpers::sanitizeBool($value);
    }
}
