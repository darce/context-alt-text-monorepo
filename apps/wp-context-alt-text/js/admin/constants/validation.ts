/**
 * Shared validation constants for frontend validation rules.
 *
 * These constants MUST match their PHP counterparts in:
 * - src/Shared/Constants/ValidationConstants.php
 * - src/Shared/Utils/ValidationHelpers.php
 *
 * Changes to these values should be synchronized across both codebases
 * to maintain contract alignment.
 */

/**
 * Timeout validation constants (milliseconds)
 */
export const TIMEOUT_MS = {
    /** Minimum allowed timeout value */
    MIN: 1_000,

    /** Maximum allowed timeout value */
    MAX: 120_000,

    /** Default timeout when value is invalid or missing */
    DEFAULT: 15_000,
} as const;

/**
 * URL validation constants
 */
export const URL_VALIDATION = {
    /** Pattern for validating URL schemes (http/https) */
    PATTERN: /^(https?:)\/\//i,

    /** List of allowed URL schemes */
    REQUIRED_SCHEMES: ["http", "https"] as const,
} as const;

/**
 * Combined validation constants
 */
export const VALIDATION = {
    TIMEOUT_MS,
    URL: URL_VALIDATION,
} as const;

// Type exports for convenience
export type TimeoutConfig = typeof TIMEOUT_MS;
export type UrlValidationConfig = typeof URL_VALIDATION;
export type ValidationConfig = typeof VALIDATION;
