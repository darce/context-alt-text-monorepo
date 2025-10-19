<?php

declare(strict_types=1);

namespace ContextAltText\Shared\Constants;

/**
 * Shared validation constants for backend validation rules.
 * 
 * These constants MUST match their TypeScript counterparts in:
 * - js/admin/constants/validation.ts
 * 
 * Changes to these values should be synchronized across both codebases
 * to maintain contract alignment.
 * 
 * @package ContextAltText\Shared\Constants
 */
final class ValidationConstants
{
    /**
     * Minimum allowed timeout value (milliseconds)
     */
    public const MIN_TIMEOUT_MS = 1000;

    /**
     * Maximum allowed timeout value (milliseconds)
     */
    public const MAX_TIMEOUT_MS = 120000;

    /**
     * Default timeout when value is invalid or missing (milliseconds)
     */
    public const DEFAULT_TIMEOUT_MS = 15000;

    /**
     * Allowed URL schemes for recognition service endpoint
     * 
     * @var array<string>
     */
    public const ALLOWED_URL_SCHEMES = ['http', 'https'];

    /**
     * URL validation pattern (matches http:// or https://)
     */
    public const URL_SCHEME_PATTERN = '/^(https?:)\/\//i';
}
