import { _n, sprintf } from "@wordpress/i18n";

/**
 * Normalize a search query string
 *
 * Trims whitespace and returns null for empty strings.
 * Used to convert empty/whitespace-only input into null for API queries.
 *
 * @param {string} value - Raw search input value
 * @returns {string | null} Trimmed string or null if empty
 *
 * @example
 * ```ts
 * normalizeSearchQuery("  hello  ")  // "hello"
 * normalizeSearchQuery("")           // null
 * normalizeSearchQuery("   ")        // null
 * ```
 */
export const normalizeSearchQuery = (value: string): string | null => {
    const trimmed = value.trim();
    return trimmed.length > 0 ? trimmed : null;
};

/**
 * Format a selection count with proper pluralization
 *
 * Uses WordPress i18n functions for proper translation and pluralization.
 *
 * @param {number} count - Number of items selected
 * @returns {string} Localized string like "1 item" or "5 items"
 *
 * @example
 * ```ts
 * formatSelectionCount(1)   // "1 item"
 * formatSelectionCount(5)   // "5 items"
 * formatSelectionCount(0)   // "0 items"
 * ```
 */
export const formatSelectionCount = (count: number): string =>
    sprintf(_n("%d item", "%d items", count, "context-alt-text"), count);
