/**
 * Primitive type normalization utilities.
 *
 * These functions provide consistent type coercion and validation
 * for data received from API responses or user input.
 */

/**
 * Convert unknown value to a finite number with fallback.
 *
 * @param value - Value to convert
 * @param fallback - Value to return if conversion fails (default: 0)
 * @returns Finite number or fallback value
 */
export const toFiniteNumber = (value: unknown, fallback = 0): number => {
    const numeric = Number(value);
    return Number.isFinite(numeric) ? numeric : fallback;
};

/**
 * Convert unknown value to number or null.
 *
 * @param value - Value to convert
 * @returns Number if valid and finite, null otherwise
 */
export const toNumberOrNull = (value: unknown): number | null => {
    const numeric = Number(value);
    return Number.isFinite(numeric) ? numeric : null;
};

/**
 * Convert unknown value to nullable timestamp (positive number).
 *
 * @param value - Value to convert
 * @returns Positive number if valid timestamp, null otherwise
 */
export const toNullableTimestamp = (value: unknown): number | null => {
    const numeric = Number(value);
    return Number.isFinite(numeric) && numeric > 0 ? numeric : null;
};

/**
 * Convert unknown value to string or null.
 *
 * @param value - Value to convert
 * @returns Non-empty string or null
 */
export const toStringOrNull = (value: unknown): string | null => {
    if (typeof value === "string") {
        const trimmed = value.trim();
        return trimmed !== "" ? trimmed : null;
    }

    if (value === undefined || value === null) {
        return null;
    }

    if (typeof value === "number" || typeof value === "boolean") {
        const stringified = String(value);
        return stringified !== "" ? stringified : null;
    }

    return null;
};

/**
 * Convert unknown value to string (empty string fallback).
 *
 * @param value - Value to convert
 * @returns String representation of value
 */
export const ensureString = (value: unknown): string => {
    if (typeof value === "string") {
        return value;
    }

    if (value === undefined || value === null) {
        return "";
    }

    if (typeof value === "number" || typeof value === "boolean") {
        return String(value);
    }

    if (typeof value === "bigint") {
        return value.toString();
    }

    if (value instanceof Date) {
        return value.toISOString();
    }

    return "";
};

/**
 * Convert unknown value to boolean or null.
 *
 * @param value - Value to convert
 * @returns Boolean if clearly truthy/falsy, null otherwise
 */
export const toBooleanOrNull = (value: unknown): boolean | null => {
    if (typeof value === "boolean") {
        return value;
    }

    if (value === null || value === undefined) {
        return null;
    }

    if (typeof value === "number") {
        return value !== 0;
    }

    if (typeof value === "string") {
        const lower = value.toLowerCase().trim();
        if (lower === "true" || lower === "1" || lower === "yes") {
            return true;
        }
        if (lower === "false" || lower === "0" || lower === "no" || lower === "") {
            return false;
        }
        return null;
    }

    return null;
};

/**
 * Convert array of mixed IDs to unique numeric IDs.
 *
 * Filters out non-numeric, zero, and negative values,
 * and removes duplicates.
 *
 * @param ids - Array of numeric or string IDs
 * @returns Array of unique positive numeric IDs
 */
export const toUniqueNumericIds = (ids: (number | string)[]): number[] => {
    const normalized = ids.map((value) => Number(value)).filter((value) => Number.isFinite(value) && value > 0);

    return Array.from(new Set(normalized));
};
