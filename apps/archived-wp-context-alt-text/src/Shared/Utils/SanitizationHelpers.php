<?php

declare(strict_types=1);

namespace ContextAltText\Shared\Utils;

use function array_filter;
use function array_map;
use function array_unique;
use function array_values;
use function filter_var;
use function is_array;
use function is_bool;
use function is_finite;
use function is_numeric;
use function is_string;
use function sanitize_text_field;
use function strtolower;
use function trim;

use const FILTER_VALIDATE_BOOLEAN;
use const FILTER_NULL_ON_FAILURE;

/**
 * Primitive type sanitization utilities.
 *
 * These functions provide consistent type coercion and validation
 * for data received from API requests or database queries.
 *
 * IMPORTANT: These sanitization patterns MUST match their TypeScript counterparts
 * in js/admin/utils/normalization/primitives.ts to maintain contract alignment.
 *
 * @package ContextAltText\Shared\Utils
 */
final class SanitizationHelpers
{
    /**
     * Convert mixed value to a finite number with fallback.
     *
     * Mirrors: toFiniteNumber() in primitives.ts
     *
     * @param mixed $value Value to convert
     * @param int|float $fallback Value to return if conversion fails (default: 0)
     * @return int|float Finite number or fallback value
     */
    public static function toFiniteNumber($value, $fallback = 0)
    {
        if (is_numeric($value)) {
            $numeric = (float) $value;
            return is_finite($numeric) ? $numeric : $fallback;
        }

        return $fallback;
    }

    /**
     * Convert mixed value to number or null.
     *
     * Mirrors: toNumberOrNull() in primitives.ts
     *
     * @param mixed $value Value to convert
     * @return int|float|null Number if valid and finite, null otherwise
     */
    public static function toNumberOrNull($value)
    {
        if (is_numeric($value)) {
            $numeric = (float) $value;
            return is_finite($numeric) ? $numeric : null;
        }

        return null;
    }

    /**
     * Convert mixed value to nullable timestamp (positive number).
     *
     * Mirrors: toNullableTimestamp() in primitives.ts
     *
     * @param mixed $value Value to convert
     * @return int|null Positive number if valid timestamp, null otherwise
     */
    public static function toNullableTimestamp($value): ?int
    {
        if (is_numeric($value)) {
            $numeric = (int) $value;
            return $numeric > 0 ? $numeric : null;
        }

        return null;
    }

    /**
     * Convert mixed value to string or null.
     *
     * Mirrors: toStringOrNull() in primitives.ts
     *
     * @param mixed $value Value to convert
     * @return string|null Non-empty sanitized string or null
     */
    public static function toStringOrNull($value): ?string
    {
        if (is_string($value)) {
            $sanitized = sanitize_text_field(trim($value));
            return $sanitized !== '' ? $sanitized : null;
        }

        if ($value === null) {
            return null;
        }

        if (is_numeric($value) || is_bool($value)) {
            $stringified = (string) $value;
            $sanitized = sanitize_text_field($stringified);
            return $sanitized !== '' ? $sanitized : null;
        }

        return null;
    }

    /**
     * Convert mixed value to string (empty string fallback).
     *
     * Mirrors: ensureString() in primitives.ts
     *
     * @param mixed $value Value to convert
     * @return string String representation of value (sanitized)
     */
    public static function ensureString($value): string
    {
        if (is_string($value)) {
            return sanitize_text_field($value);
        }

        if ($value === null) {
            return '';
        }

        if (is_numeric($value) || is_bool($value)) {
            return sanitize_text_field((string) $value);
        }

        return '';
    }

    /**
     * Convert mixed value to boolean or null.
     *
     * Mirrors: toBooleanOrNull() in primitives.ts
     *
     * @param mixed $value Value to convert
     * @return bool|null Boolean if clearly truthy/falsy, null otherwise
     */
    public static function toBooleanOrNull($value): ?bool
    {
        if (is_bool($value)) {
            return $value;
        }

        if ($value === null) {
            return null;
        }

        if (is_numeric($value)) {
            return $value !== 0 && $value !== 0.0;
        }

        if (is_string($value)) {
            $lower = strtolower(trim($value));

            if ($lower === 'true' || $lower === '1' || $lower === 'yes') {
                return true;
            }

            if ($lower === 'false' || $lower === '0' || $lower === 'no' || $lower === '') {
                return false;
            }

            return null;
        }

        return null;
    }

    /**
     * Convert array of mixed IDs to unique numeric IDs.
     *
     * Filters out non-numeric, zero, and negative values,
     * and removes duplicates.
     *
     * Mirrors: toUniqueNumericIds() in primitives.ts
     *
     * @param array<int|string> $ids Array of numeric or string IDs
     * @return array<int> Array of unique positive numeric IDs
     */
    public static function toUniqueNumericIds(array $ids): array
    {
        $normalized = array_map(
            static function ($value): ?int {
                if (is_numeric($value)) {
                    $numeric = (int) $value;
                    return $numeric > 0 ? $numeric : null;
                }
                return null;
            },
            $ids
        );

        // Filter out nulls
        $filtered = array_filter($normalized, static function ($value): bool {
            return $value !== null;
        });

        // Remove duplicates and re-index
        return array_values(array_unique($filtered));
    }

    /**
     * Sanitize and validate a boolean value (strict).
     *
     * This is the existing sanitizeBool method, kept for backwards compatibility.
     * For new code, prefer toBooleanOrNull() for nullable boolean handling.
     *
     * @param mixed $value Value to convert to boolean
     * @return bool Sanitized boolean value (never null)
     */
    public static function sanitizeBool($value): bool
    {
        if (is_bool($value)) {
            return $value;
        }

        if (is_string($value)) {
            $value = trim($value);
        }

        if (is_numeric($value) || is_string($value)) {
            return filter_var($value, FILTER_VALIDATE_BOOLEAN, FILTER_NULL_ON_FAILURE) ?? false;
        }

        return false;
    }
}
